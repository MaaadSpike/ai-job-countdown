"""按领域抓 AI 进展新闻，写进网站用的 web/news.json。

流程：
1. 每个领域（news/fields.json，按 SOC 大类）拼一个 Google News RSS 搜索词，抓最近 --days 天的新闻
2. 筛选：配了 LLM 就让模型挑出真正和 AI 能力进展 / 现实检验相关的条目，翻译成中文并分类；
   没配就用关键词规则（标题里要有 AI 词和领域词），只保留英文标题
3. 和上次的 web/news.json 合并去重；人工挑选的 news/curated.json 每次原样并入
4. 每个领域最多留 --keep 条自动新闻，超过 --max-age 天的自动新闻丢掉
5. 条目没变就不改文件（定时任务据此决定要不要提交）

LLM 用任何 OpenAI 兼容接口（OpenAI、DeepSeek、通义、自己起的 vllm serve 都行），通过环境变量配置：
    NEWS_LLM_API_KEY    不设就走关键词规则
    NEWS_LLM_BASE_URL   默认 https://api.openai.com/v1
    NEWS_LLM_MODEL      默认 gpt-4o-mini

用法：
    python news/collect.py                       # 全部领域
    python news/collect.py --fields 15,23 -v     # 只抓两个领域，打印细节
    python news/collect.py --curated-only        # 不联网，只把 curated.json 写进 news.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
UA = "Mozilla/5.0 (compatible; ai-job-countdown-news/1.0; +https://github.com/MaaadSpike/ai-job-countdown)"

# 关键词规则（没配 LLM 时用）
AI_WORDS = re.compile(r"\b(ai|a\.i\.|artificial intelligence|llms?|gpt|chatgpt|claude|gemini|copilot|agents?|agentic|"
                      r"machine learning|deep learning|neural|robots?|robotic|robotics|humanoids?|autonomous|self-driving|driverless|robotaxis?)\b", re.I)
CHECK_WORDS = re.compile(r"\b(fail|fails|failed|failure|slower|hallucinat\w*|fabricat\w*|sanction\w*|lawsuit|sued|backlash|"
                         r"rehir\w*|reverses?|flaw\w*|errors?|mistakes?|limits?|limitations?|struggl\w*|worse|"
                         r"overhyped|hype|doubts?|skeptic\w*|recall\w*|banned?|pause[sd]?|halt\w*|crash\w*)\b", re.I)
# 和「AI 能力进展」无关的常见噪音：股价、融资、财报
NOISE_WORDS = re.compile(r"\b(stocks?|shares?|nasdaq|dow|s&p|earnings|ipo|valuation|raises \$|funding round|price target|"
                         r"buy rating|etf|dividend|crypto)\b", re.I)


# ---------------------------------------------------------------- 抓取和解析

def build_query(field: dict, ai_terms: list[str], days: int) -> str:
    return f"({' OR '.join(ai_terms)}) ({' OR '.join(field['terms'])}) when:{days}d"


def rss_url(query: str) -> str:
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})


def fetch(url: str, retries: int = 2, timeout: int = 20) -> bytes:
    err = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # 网络抖动重试
            err = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed: {url}: {err}")


def parse_rss(xml: bytes) -> list[dict]:
    """Google News RSS → [{title, src, url, date}]。标题末尾的「 - 来源」会去掉。"""
    out = []
    root = ET.fromstring(xml)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        url = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        src = (src_el.text or "").strip() if src_el is not None else ""
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        elif not src and " - " in title:
            title, src = title.rsplit(" - ", 1)
        try:
            date = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(timezone.utc).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            date = ""
        if title and url and date:
            out.append({"title": title, "src": src, "url": url, "date": date})
    return out


# ---------------------------------------------------------------- 筛选

def norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", " ", s.lower()).strip()


def item_id(url: str, title: str) -> str:
    return hashlib.sha1((url + "|" + norm_title(title)).encode("utf-8")).hexdigest()[:12]


def term_regex(terms: list[str]) -> re.Pattern:
    # 粗略取词干，允许词尾变化：radiology → radiol*（能匹配 radiologists），mathematics → mathemat*
    parts = []
    for t in terms:
        w = t.strip('"').lower()
        head, _, last = w.rpartition(" ")
        stem = last[:max(5, len(last) - 3)]
        parts.append(re.escape((head + " " if head else "") + stem))
    return re.compile(r"\b(" + "|".join(parts) + r")", re.I)


def keyword_filter(cands: list[dict], field: dict, limit: int) -> list[dict]:
    """没有 LLM 时：标题里同时有 AI 词和领域词，不是股价融资新闻。反面词 → check，其余 → signal。"""
    fre = term_regex(field["terms"])
    kept = []
    for c in cands:
        t = c["title"]
        if not (AI_WORDS.search(t) and fre.search(t)) or NOISE_WORDS.search(t):
            continue
        kept.append({**c, "k": "check" if CHECK_WORDS.search(t) else "signal", "zh": None, "en": t})
        if len(kept) >= limit:
            break
    return kept


LLM_SYSTEM = """You curate news for a website that projects when AI could handle the work of each occupation.
You get recent headlines for one occupational field. Keep only headlines that report concrete evidence about what AI (including agents and AI-driven robots) can or cannot do in THIS field's work:
- "signal": a concrete capability advance or real deployment that does part of this field's work (a model solving a problem, a system doing a task end to end, a company actually replacing or automating a workflow, a benchmark result tied to this kind of work)
- "check": concrete evidence of limits: failures, errors, hallucinations, sanctions, reversals, rehiring humans, studies showing no gain, slow adoption
Drop: funding, stock prices, earnings, product launches with no capability claim, opinion and listicles, generic "AI will change X" pieces, policy debates with no deployment, events, and near-duplicates of a story you already kept.
For each kept headline give a faithful Chinese translation ("zh") and a clean English headline ("en"). Do not add any fact that is not in the headline.
Return JSON only: {"items": [{"i": <index>, "k": "signal" | "check", "zh": "...", "en": "..."}]}, best first, at most LIMIT items. Return {"items": []} if nothing qualifies."""


def llm_filter(cands: list[dict], field: dict, limit: int, cfg: dict) -> list[dict]:
    if not cands:
        return []
    lines = "\n".join(f"[{i}] {c['title']} ({c['src']}, {c['date']})" for i, c in enumerate(cands))
    body = {
        "model": cfg["model"],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": LLM_SYSTEM.replace("LIMIT", str(limit))},
            {"role": "user", "content": f"Field: {field['en']}\nHeadlines:\n{lines}"},
        ],
    }
    req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + cfg["api_key"]})
    with urllib.request.urlopen(req, timeout=120) as r:
        content = json.loads(r.read())["choices"][0]["message"]["content"]
    return parse_llm(content, cands, limit)


def parse_llm(content: str, cands: list[dict], limit: int) -> list[dict]:
    m = re.search(r"\{.*\}", content, re.S)
    data = json.loads(m.group(0) if m else content)
    kept, seen = [], set()
    for x in data.get("items", []):
        i = x.get("i")
        if not isinstance(i, int) or not 0 <= i < len(cands) or i in seen:
            continue
        seen.add(i)
        k = x.get("k") if x.get("k") in ("signal", "check") else "signal"
        en = (x.get("en") or cands[i]["title"]).strip()
        zh = (x.get("zh") or "").strip() or None
        kept.append({**cands[i], "k": k, "zh": zh, "en": en})
        if len(kept) >= limit:
            break
    return kept


# ---------------------------------------------------------------- 合并

def to_item(c: dict, code: str) -> dict:
    it = {"id": item_id(c["url"], c["title"]), "k": c["k"], "date": c["date"], "src": c["src"], "url": c["url"],
          "fields": [code], "en": {"t": c["en"]}}
    if c.get("zh"):
        it["zh"] = {"t": c["zh"]}
    return it


def curated_items(path: Path) -> list[dict]:
    out = []
    for c in json.loads(path.read_text(encoding="utf-8"))["items"]:
        out.append({"id": item_id(c["url"], c["en"]["t"]), "k": c["k"], "date": c["date"], "src": c["src"], "url": c["url"],
                    "fields": c["fields"], "occ": c.get("occ", []), "curated": True, "zh": c["zh"], "en": c["en"]})
    return out


def merge(old_auto: list[dict], new_auto: list[dict], keep: int, max_age: int, today: datetime) -> list[dict]:
    """新旧自动新闻合并：同一条（同 id 或同标题）合并领域；按领域各留最新 keep 条；太旧的丢掉。"""
    cutoff = (today - timedelta(days=max_age)).strftime("%Y-%m-%d")
    by_key: dict[str, dict] = {}
    for it in old_auto + new_auto:
        if it["date"] < cutoff:
            continue
        key = norm_title(it["en"]["t"])
        cur = by_key.get(key) or next((v for v in by_key.values() if v["id"] == it["id"]), None)
        if cur:
            cur["fields"] = sorted(set(cur["fields"]) | set(it["fields"]))
            if "zh" not in cur and "zh" in it:
                cur["zh"] = it["zh"]
        else:
            by_key[key] = json.loads(json.dumps(it))
    items = sorted(by_key.values(), key=lambda x: (x["date"], x["id"]), reverse=True)
    count: dict[str, int] = {}
    out = []
    for it in items:
        live = [f for f in it["fields"] if count.get(f, 0) < keep]
        if not live:
            continue
        for f in live:
            count[f] = count.get(f, 0) + 1
        it["fields"] = live
        out.append(it)
    return out


def collect(fields_cfg: dict, only: set[str] | None, days: int, per_field: int, fetcher, filt, verbose=False):
    """返回 (新自动条目, 失败的领域)。fetcher(url)->bytes，filt(cands, field, limit)->kept。"""
    new, failed = [], []
    for code, field in fields_cfg["fields"].items():
        if only and code not in only:
            continue
        url = rss_url(build_query(field, fields_cfg["ai_terms"], days))
        try:
            cands = parse_rss(fetcher(url))
            kept = filt(cands, field, per_field)
        except Exception as e:
            print(f"[{code}] {field['en']}: 失败 {e}", file=sys.stderr)
            failed.append(code)
            continue
        if verbose:
            print(f"[{code}] {field['en']}: {len(cands)} 条候选 → 保留 {len(kept)}")
            for c in kept:
                print(f"    {c['k']:6} {c['date']} {c['en'][:90]}")
        new += [to_item(c, code) for c in kept]
    return new, failed


def build(fields_cfg: dict, curated: list[dict], auto: list[dict], updated: str) -> dict:
    fields = {k: {"zh": v["zh"], "en": v["en"]} for k, v in fields_cfg["fields"].items()}
    items = sorted(curated + auto, key=lambda x: (x["date"], x["id"]), reverse=True)
    return {"updated": updated, "fields": fields, "items": items}


def main(argv=None):
    ap = argparse.ArgumentParser(description="按领域抓 AI 新闻 → web/news.json")
    ap.add_argument("--out", default=str(ROOT / "web" / "news.json"))
    ap.add_argument("--fields-file", default=str(HERE / "fields.json"))
    ap.add_argument("--curated", default=str(HERE / "curated.json"))
    ap.add_argument("--fields", help="只抓这些领域，逗号分隔，比如 15,23")
    ap.add_argument("--days", type=int, default=14, help="抓最近多少天的新闻")
    ap.add_argument("--per-field", type=int, default=4, help="每次每个领域最多新增几条")
    ap.add_argument("--keep", type=int, default=12, help="每个领域最多保留几条自动新闻")
    ap.add_argument("--max-age", type=int, default=180, help="自动新闻保留多少天")
    ap.add_argument("--curated-only", action="store_true", help="不联网，只更新人工挑选的部分")
    ap.add_argument("--sleep", type=float, default=1.0, help="两次请求之间等几秒")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    fields_cfg = json.loads(Path(args.fields_file).read_text(encoding="utf-8"))
    curated = curated_items(Path(args.curated))
    out = Path(args.out)
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"items": []}
    old_auto = [it for it in old.get("items", []) if not it.get("curated")]
    now = datetime.now(timezone.utc)

    new_auto, failed = [], []
    if not args.curated_only:
        api_key = os.environ.get("NEWS_LLM_API_KEY", "").strip()
        if api_key:
            cfg = {"api_key": api_key, "base_url": os.environ.get("NEWS_LLM_BASE_URL") or "https://api.openai.com/v1",
                   "model": os.environ.get("NEWS_LLM_MODEL") or "gpt-4o-mini"}
            def filt(c, f, n):
                return llm_filter(c, f, n, cfg)
            print(f"筛选：LLM（{cfg['model']}）")
        else:
            filt = keyword_filter
            print("筛选：关键词规则（没设 NEWS_LLM_API_KEY，只保留英文标题）")

        def fetcher(u):
            time.sleep(args.sleep)
            return fetch(u)
        only = set(args.fields.split(",")) if args.fields else None
        new_auto, failed = collect(fields_cfg, only, args.days, args.per_field, fetcher, filt, args.verbose)
        n_tried = len(only) if only else len(fields_cfg["fields"])
        if failed and len(failed) == n_tried:
            print("所有领域都抓取失败，不改动 news.json", file=sys.stderr)
            return 1

    auto = merge(old_auto, new_auto, args.keep, args.max_age, now)
    data = build(fields_cfg, curated, auto, now.strftime("%Y-%m-%dT%H:%MZ"))
    if old.get("items") == data["items"] and old.get("fields") == data["fields"]:
        print("没有新条目，news.json 不变")
        return 0
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n_new = len({i["id"] for i in auto} - {i["id"] for i in old_auto})
    print(f"写入 {out}：{len(curated)} 条人工 + {len(auto)} 条自动（新增 {n_new}）" + (f"；失败领域 {failed}" if failed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
