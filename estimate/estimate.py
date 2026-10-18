"""M2：批量估计每条任务的端到端时长和任务类型。

三种后端，同一份 prompt 和输出格式：
- vllm   在租来的 GPU 上直接用 vLLM 离线批量推理（默认，最快最便宜）
- openai 调任何 OpenAI 兼容接口（vllm serve 起的服务，或托管 API），作为备用
- mock   不调模型，随机生成结果，用来在没有 GPU 的机器上测试整条流程

特性：
- 分批处理，每批写入 raw.jsonl；中断后重跑同一条命令会跳过已完成的任务
- 每条任务采样 n 次（默认 5），汇总时取对数时长的中位数，类型取多数票
- 记录吞吐量（tokens/s）和按 GPU 时价估算的成本，写进 run_stats.json

用法：
    python estimate.py --tasks tasks.jsonl --out runs/v1 --limit 50          # 先小规模试
    python estimate.py --tasks tasks.jsonl --out runs/v1 --gpu-price 1.9     # 全量
    python estimate.py --tasks tasks.jsonl --out runs/v1 --aggregate-only    # 只重新汇总
"""
import argparse
import json
import math
import random
import statistics
import time
from collections import Counter
from pathlib import Path

from prompt import PROMPT_VERSION, SCHEMA, TASK_TYPES, build_messages, parse


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def key(row: dict) -> str:
    return f"{row['onet_code']}|{row['task_id']}"


class VLLMBackend:
    def __init__(self, args):
        from vllm import LLM, SamplingParams
        # 所有请求共用同一段很长的 system prompt，打开 prefix caching 只算一次
        self.llm = LLM(model=args.model, max_model_len=args.max_model_len, enable_prefix_caching=True,
                       gpu_memory_utilization=args.gpu_mem, tensor_parallel_size=args.tp)
        kw = dict(n=args.n, temperature=args.temperature, top_p=0.95, max_tokens=args.max_tokens, seed=args.seed)
        guided = None
        try:  # vLLM 各版本的结构化输出接口名字不同，依次尝试
            from vllm.sampling_params import GuidedDecodingParams
            guided = {"guided_decoding": GuidedDecodingParams(json=SCHEMA)}
        except ImportError:
            try:
                from vllm.sampling_params import StructuredOutputsParams
                guided = {"structured_outputs": StructuredOutputsParams(json=SCHEMA)}
            except ImportError:
                print("提示：这个 vLLM 版本没有找到结构化输出接口，改用普通生成 + JSON 解析")
        try:
            self.params = SamplingParams(**kw, **(guided or {}))
        except TypeError:
            self.params = SamplingParams(**kw)
        self.model = args.model

    def run(self, rows):
        outs = self.llm.chat([build_messages(r) for r in rows], self.params, use_tqdm=False)
        results = []
        for o in outs:
            texts = [c.text for c in o.outputs]
            ntok = sum(len(c.token_ids) for c in o.outputs)
            results.append((texts, len(o.prompt_token_ids or []), ntok))
        return results


class OpenAIBackend:
    def __init__(self, args):
        from concurrent.futures import ThreadPoolExecutor
        from openai import OpenAI
        self.client = OpenAI(base_url=args.base_url, api_key=args.api_key or "EMPTY")
        self.pool = ThreadPoolExecutor(args.concurrency)
        self.args = args
        self.model = args.model

    def _one(self, r):
        a = self.args
        resp = self.client.chat.completions.create(
            model=a.model, messages=build_messages(r), n=a.n, temperature=a.temperature,
            max_tokens=a.max_tokens, response_format={"type": "json_object"})
        texts = [c.message.content for c in resp.choices]
        u = resp.usage
        return texts, (u.prompt_tokens if u else 0), (u.completion_tokens if u else 0)

    def run(self, rows):
        return list(self.pool.map(self._one, rows))


class MockBackend:
    def __init__(self, args):
        self.rng = random.Random(args.seed)
        self.n = args.n
        self.model = "mock"

    def run(self, rows):
        out = []
        for _ in rows:
            texts = []
            for _ in range(self.n):
                mid = math.exp(self.rng.uniform(math.log(0.1), math.log(300)))
                texts.append(json.dumps({"reasoning": "mock", "hours_low": mid / 2, "hours_typical": mid,
                                         "hours_high": mid * 2, "task_type": self.rng.choice(TASK_TYPES)}))
            out.append((texts, 300, 60 * self.n))
        return out


def aggregate(raw: list[dict]) -> list[dict]:
    rows = []
    for r in raw:
        parsed = [p for p in (parse(t) for t in r["outputs"]) if p]
        base = {k: r[k] for k in ("task_id", "onet_code", "occupation", "task")}
        if not parsed:
            rows.append({**base, "n_valid": 0})
            continue
        logs = [math.log(p["hours_typical"]) for p in parsed]
        votes = Counter(p["task_type"] for p in parsed)
        top_type, top_n = votes.most_common(1)[0]
        rows.append({
            **base,
            "hours": math.exp(statistics.median(logs)),
            "hours_low": math.exp(statistics.median(math.log(p["hours_low"]) for p in parsed)),
            "hours_high": math.exp(statistics.median(math.log(p["hours_high"]) for p in parsed)),
            "sample_spread_doublings": (max(logs) - min(logs)) / math.log(2),
            "task_type": top_type,
            "type_agreement": top_n / len(parsed),
            "n_valid": len(parsed),
            "reasoning": parsed[0]["reasoning"],
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, default=Path("tasks.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("runs/v1"))
    ap.add_argument("--backend", choices=["vllm", "openai", "mock"], default="vllm")
    ap.add_argument("--model", default="Qwen/Qwen2.5-32B-Instruct-AWQ")
    ap.add_argument("--n", type=int, default=5, help="每条任务采样几次")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=300)
    ap.add_argument("--batch-size", type=int, default=512)
    ap.add_argument("--limit", type=int, help="只跑前 N 条（试 prompt 用）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-model-len", type=int, default=4096)
    ap.add_argument("--gpu-mem", type=float, default=0.90)
    ap.add_argument("--tp", type=int, default=1, help="tensor parallel：用几张卡")
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--gpu-price", type=float, default=None, help="GPU 每小时价格（美元），用来估算成本")
    ap.add_argument("--aggregate-only", action="store_true")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    raw_path, agg_path, stats_path = args.out / "raw.jsonl", args.out / "estimates.jsonl", args.out / "run_stats.json"

    if not args.aggregate_only:
        tasks = read_jsonl(args.tasks)
        if args.limit:
            tasks = tasks[: args.limit]
        done = {key(r) for r in read_jsonl(raw_path)}
        todo = [t for t in tasks if key(t) not in done]
        print(f"共 {len(tasks)} 条，已完成 {len(tasks) - len(todo)} 条，本次要跑 {len(todo)} 条")
    if not args.aggregate_only and todo:
        backend = {"vllm": VLLMBackend, "openai": OpenAIBackend, "mock": MockBackend}[args.backend](args)
        t0 = time.time()
        in_tok = out_tok = 0
        with raw_path.open("a", encoding="utf-8") as f:
            for i in range(0, len(todo), args.batch_size):
                batch = todo[i: i + args.batch_size]
                bt = time.time()
                for row, (texts, pt, ct) in zip(batch, backend.run(batch)):
                    f.write(json.dumps({**row, "outputs": texts, "model": backend.model,
                                        "prompt_version": PROMPT_VERSION}, ensure_ascii=False) + "\n")
                    in_tok += pt
                    out_tok += ct
                f.flush()
                el = time.time() - t0
                print(f"  {min(i + args.batch_size, len(todo))}/{len(todo)} 条 · 本批 {time.time() - bt:.0f}s · "
                      f"输出 {out_tok / max(el, 1e-9):.0f} tokens/s · 累计 {el / 60:.1f} 分钟")
        elapsed = time.time() - t0
        stats = {"model": backend.model, "backend": args.backend, "prompt_version": PROMPT_VERSION,
                 "n_tasks": len(todo), "samples_per_task": args.n, "elapsed_s": round(elapsed, 1),
                 "prompt_tokens": in_tok, "output_tokens": out_tok,
                 "output_tokens_per_s": round(out_tok / max(elapsed, 1e-9), 1),
                 "tasks_per_min": round(len(todo) / max(elapsed / 60, 1e-9), 1)}
        if args.gpu_price:
            stats["est_cost_usd"] = round(elapsed / 3600 * args.gpu_price, 2)
            stats["usd_per_1k_tasks"] = round(stats["est_cost_usd"] / max(len(todo), 1) * 1000, 3)
        prev = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else []
        stats_path.write_text(json.dumps(prev + [stats], indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(stats, ensure_ascii=False))

    agg = aggregate(read_jsonl(raw_path))
    with agg_path.open("w", encoding="utf-8") as f:
        for r in agg:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    bad = sum(1 for r in agg if r["n_valid"] == 0)
    print(f"汇总写入 {agg_path}：{len(agg)} 条，其中 {bad} 条没有一次有效输出")


if __name__ == "__main__":
    main()
