"""AI 标注者：按 GUIDELINES.md 的同一套规则，让一个大模型给 eval_sample.csv 里的任务标「时长档 + 类型」。

输出和人工标注页完全一样的 labels_<名字>.csv，所以 agreement.py 和 evaluate.py 可以直接用。

注意：
- 标注 prompt 只用人工标注规则，不用 M2 的 prompt 和校准例子，也不给模型看 M2 的估计，尽量保持独立。
- 最好用和 M2（Qwen）不同家族的模型，比如 Claude、GPT、DeepSeek。同家族的模型容易犯同样的错，一致率会虚高。
- 对外报告时写「与 AI 标注者的一致率」，不要写成「人工校验」或「准确率」。

后端：任何 OpenAI 兼容接口（OpenAI、DeepSeek、Anthropic 的 OpenAI 兼容端点、vllm serve 都行），
另有 mock 后端用来测试。

用法（在 annotate/ 目录）：
    # 1) 先在已有人工标注的条目上检验 AI 标注者本身
    python ai_label.py --items 1-51 --name ai-deepseek --base-url https://api.deepseek.com/v1 --model deepseek-chat
    python agreement.py labels_spike.csv labels_ai-deepseek.csv

    # 2) 再标独立测试集
    python ai_label.py --items 51-100 --name ai-deepseek --base-url https://api.deepseek.com/v1 --model deepseek-chat

    # Gemini（OpenAI 兼容端点，key 在 Google AI Studio 申请）
    python ai_label.py --items 1-53 --name ai-gemini \
        --base-url https://generativelanguage.googleapis.com/v1beta/openai/ --model gemini-3.8-flash --reasoning-effort low

API key 从 --api-key 或环境变量 AI_LABEL_API_KEY 读取。中断后重跑同一条命令会跳过已经标过的条目。
"""
import argparse
import json
import os
import random
import re
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROMPT_VERSION = "ai-label-v1"
TYPES = ["digital", "physical", "trust"]
BINS = {
    1: "under 15 minutes",
    2: "15 minutes to 1 hour",
    3: "1 to 4 hours",
    4: "4 to 8 hours (about one working day)",
    5: "1 to 5 days (8 to 40 hours)",
    6: "1 to 4 weeks (40 to 160 hours)",
    7: "1 to 3 months (160 to 500 hours)",
    8: "more than 3 months (over 500 hours)",
}
COLUMNS = ["task_id", "annotator", "duration_bin", "task_type", "skipped", "note", "labeled_at"]

# 与 GUIDELINES.md 和标注页的说明一一对应；改规则时两边一起改，并改 PROMPT_VERSION
SYSTEM = """You are an annotator labeling O*NET work tasks for a research dataset. Follow these rules exactly; they are the same rules the human annotators follow.

## 1. Duration: total focused working time for a skilled worker to complete ONE instance end to end

- One instance: doing the task completely once. "Prepare tax returns" = one return, not the total time spent on returns in a year.
- End to end: from starting to delivering the result. If it spans several days, add up the hours actually worked each day.
- Do not count waiting: approvals, replies, materials arriving, machines running.
- Skilled: someone with several years in this occupation who already knows the relevant materials and systems, so no time to learn context.
- No AI: assume the worker does not use generative AI tools.
- If the statement lists several activities, estimate the main one.
- If the scale is unclear (for example, how big a project), assume the most common case for this occupation and state your assumption in the note.
- If you are torn between two bins, pick the more likely one and say so in the note.

Pick one duration bin:
{bins}

## 2. Type: check in this order and stop at the first that applies

1. physical: the worker must handle physical objects or be physically present on site to do it.
2. trust: it does not require being on site, but its value comes mainly from in-person communication, persuasion, or building trust (counseling, negotiating, calming people, interviewing).
3. digital: everything else. The core output is text, numbers, code, images, or files, and it can be done at a computer.

Additional conventions:
- Visiting a site once or twice as one step, when the core output is a document, is digital.
- Meetings and back-and-forth with colleagues to complete a digital task do not change the type; it stays digital.
- Examples: writing nursing notes, drafting a contract, building a report, designing a poster = digital. Giving a patient IV medication, fixing a pipe, a site inspection, driving a delivery = physical. Explaining a tax plan to a client, calming an upset customer, negotiating contract terms, interviewing a candidate = trust.
- If truly mixed, pick the closest and write "mixed" and why in the note.

## 3. Skipping

If you genuinely do not understand what the task involves in this occupation, set "skip" to true instead of guessing.

Answer with JSON only:
{{"instance": "<one sentence: what one instance consists of>", "duration_bin": <1-8>, "task_type": "digital" | "physical" | "trust", "skip": false, "note": "<assumptions, or empty>"}}"""

USER = """Occupation: {occupation} (O*NET-SOC {onet_code})
{description}Task: {task}"""


def build_messages(row: dict) -> list[dict]:
    desc = str(row.get("occupation_description") or "").strip()
    return [
        {"role": "system", "content": SYSTEM.format(bins="\n".join(f"{k}. {v}" for k, v in BINS.items()))},
        {"role": "user", "content": USER.format(occupation=row["occupation"], onet_code=row["onet_code"], task=row["task"],
                                                description=f"Occupation description: {desc}\n" if desc else "")},
    ]


_JSON_RE = re.compile(r"\{.*\}", re.S)


def parse(text: str) -> dict | None:
    """解析模型输出；结构不对就返回 None（这次作废，重试）。"""
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if d.get("skip") is True:
        return {"skip": True, "note": str(d.get("note") or d.get("instance") or "")[:300]}
    try:
        b = int(d["duration_bin"])
    except (KeyError, TypeError, ValueError):
        return None
    t = str(d.get("task_type", "")).strip().lower()
    if b not in BINS or t not in TYPES:
        return None
    note = " | ".join(x for x in (str(d.get("instance") or "").strip(), str(d.get("note") or "").strip()) if x)
    return {"skip": False, "duration_bin": b, "task_type": t, "note": note[:300]}


def combine(parsed: list[dict]) -> dict | None:
    """多次采样合成一条：时长取中位数档（偶数次取较低的中位数），类型取多数票。"""
    ok = [p for p in parsed if p and not p["skip"]]
    if not ok:
        skips = [p for p in parsed if p and p["skip"]]
        return {"skip": True, "note": skips[0]["note"]} if skips else None
    b = int(statistics.median_low(p["duration_bin"] for p in ok))
    t, n = Counter(p["task_type"] for p in ok).most_common(1)[0]
    note = ok[0]["note"]
    if len(ok) > 1:
        note = f"[{len(ok)} 次采样：档 {sorted(p['duration_bin'] for p in ok)}，类型 {t} {n}/{len(ok)}] " + note
    return {"skip": False, "duration_bin": b, "task_type": t, "note": note[:300]}


class OpenAIBackend:
    def __init__(self, a):
        key = (a.api_key or os.environ.get("AI_LABEL_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
        if not key:
            sys.exit("缺少 API key：用 --api-key 或设置环境变量 AI_LABEL_API_KEY")
        if not key.isascii() or " " in key:
            sys.exit(f"API key 看起来不对（以「{key[:6]}」开头，含中文或空格）。"
                     "把 AI_LABEL_API_KEY 设成接口后台给你的真实 key，一般以 sk- 开头。")
        from openai import OpenAI  # 先检查 key 再导入，key 不对时不需要装 openai 也能看到提示
        self.client = OpenAI(base_url=a.base_url, api_key=key)
        self.a = a

    def __call__(self, messages: list[dict]) -> str:
        kw = dict(model=self.a.model, messages=messages, temperature=self.a.temperature, max_tokens=self.a.max_tokens)
        if self.a.json_mode:
            kw["response_format"] = {"type": "json_object"}
        if self.a.reasoning_effort:  # Gemini、o 系列等会先思考的模型：思考 token 也算在 max_tokens 里
            kw["reasoning_effort"] = self.a.reasoning_effort
        return self.client.chat.completions.create(**kw).choices[0].message.content


class MockBackend:
    def __init__(self, a):
        self.rng = random.Random(a.seed)

    def __call__(self, messages: list[dict]) -> str:
        return json.dumps({"instance": "mock", "duration_bin": self.rng.randint(1, 8),
                           "task_type": self.rng.choice(TYPES), "skip": False, "note": ""})


class FatalError(Exception):
    """重试也没用的错误（key 不对、模型名不对、地址不对），整批停下。"""


FATAL_NAMES = {"AuthenticationError", "PermissionDeniedError", "NotFoundError", "BadRequestError", "UnicodeEncodeError"}


def label_one(call, row: dict, samples: int, retries: int = 3) -> dict | None:
    parsed = []
    for _ in range(samples):
        p = None
        for attempt in range(retries + 1):
            if attempt:
                time.sleep(2 * attempt)  # 限流（429）时等一会儿再试
            try:
                p = parse(call(build_messages(row)))
            except Exception as e:  # 网络或限流：重试；配置错误：直接停
                if type(e).__name__ in FATAL_NAMES:
                    raise FatalError(f"{type(e).__name__}: {e}") from e
                print(f"  第 {row['item_no']} 条请求出错，重试：{str(e)[:200]}", file=sys.stderr)
            if p:
                break
        parsed.append(p)
    return combine(parsed)


def save(done: pd.DataFrame, new: list[dict], out: Path) -> pd.DataFrame:
    all_rows = pd.concat([done, pd.DataFrame(new, columns=COLUMNS)], ignore_index=True)
    if len(all_rows):  # 一条都没有就不写空文件，免得 agreement.py 读到空表
        all_rows.to_csv(out, index=False, encoding="utf-8-sig")
    return all_rows


def parse_items(spec: str) -> set[int]:
    out = set()
    for part in spec.split(","):
        lo, _, hi = part.strip().partition("-")
        out |= set(range(int(lo), int(hi or lo) + 1))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI 标注者：按 GUIDELINES.md 标 eval_sample.csv")
    ap.add_argument("--sample", type=Path, default=Path("eval_sample.csv"))
    ap.add_argument("--items", required=True, help="要标的条目编号（item_no），比如 1-51 或 51-100 或 1-20,51-100")
    ap.add_argument("--name", required=True, help="标注者名字，输出 labels_<名字>.csv，比如 ai-deepseek")
    ap.add_argument("--backend", choices=["openai", "mock"], default="openai")
    ap.add_argument("--base-url", default="https://api.openai.com/v1")
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--samples", type=int, default=1, help="每条采样几次（>1 时时长取中位数档、类型取多数票）")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=2000, help="输出上限；会思考的模型（Gemini 等）思考也算在内")
    ap.add_argument("--reasoning-effort", choices=["none", "minimal", "low", "medium", "high"],
                    help="会思考的模型设成 minimal 或 low，省钱也更快")
    ap.add_argument("--no-json-mode", dest="json_mode", action="store_false",
                    help="接口不支持 response_format 时加这个")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)

    sample = pd.read_csv(a.sample, dtype={"task_id": str, "onet_code": str}).fillna("")
    want = parse_items(a.items)
    rows = sample[sample["item_no"].astype(int).isin(want)].sort_values("item_no")
    out = Path(f"labels_{re.sub(r'[^A-Za-z0-9_-]+', '_', a.name)}.csv")
    done = pd.read_csv(out, dtype={"task_id": str}) if out.exists() else pd.DataFrame(columns=COLUMNS)
    todo = rows[~rows["task_id"].isin(set(done["task_id"]))].to_dict("records")
    print(f"要标 {len(rows)} 条，已标 {len(rows) - len(todo)} 条，本次 {len(todo)} 条 → {out}")
    if not todo:
        return 0

    call = {"openai": OpenAIBackend, "mock": MockBackend}[a.backend](a)
    model = a.model if a.backend == "openai" else "mock"
    new, failed = [], []
    with ThreadPoolExecutor(a.concurrency) as pool:
        futures = [pool.submit(label_one, call, r, a.samples) for r in todo]
        for row, fut in zip(todo, futures):
            try:
                res = fut.result()
            except FatalError as e:
                for f in futures:
                    f.cancel()
                save(done, new, out)
                sys.exit(f"停止：{e}\n检查 --base-url、--model 和 API key 是否正确。已标的 {len(new)} 条已保存。")
            if res is None:
                failed.append(int(row["item_no"]))
                continue
            new.append({"task_id": row["task_id"], "annotator": a.name,
                        "duration_bin": None if res["skip"] else res["duration_bin"],
                        "task_type": None if res["skip"] else res["task_type"],
                        "skipped": int(res["skip"]),
                        "note": f"{model} · {PROMPT_VERSION} · {res['note']}",
                        "labeled_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    all_rows = save(done, new, out)
    print(f"新标 {len(new)} 条（跳过 {sum(r['skipped'] for r in new)} 条），共 {len(all_rows)} 条")
    if failed:
        print(f"{len(failed)} 条没有拿到有效输出，重跑同一条命令会再试：{failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
