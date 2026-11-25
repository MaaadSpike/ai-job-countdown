"""news/collect.py：RSS 解析、关键词筛选、LLM 输出解析、合并去重，以及 web/news.json 的格式。不联网。"""
import json
from datetime import datetime, timezone
from pathlib import Path

import collect
import pytest

ROOT = Path(__file__).resolve().parents[1]

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>t</title>
<item><title>AI model reads chest X-rays as well as radiologists - Reuters</title>
 <link>https://news.google.com/rss/articles/aaa</link><pubDate>Mon, 23 Nov 2026 14:00:00 GMT</pubDate>
 <source url="https://www.reuters.com">Reuters</source></item>
<item><title>Hospital pauses AI triage tool after diagnosis errors - STAT</title>
 <link>https://news.google.com/rss/articles/bbb</link><pubDate>Sun, 22 Nov 2026 09:30:00 GMT</pubDate>
 <source url="https://www.statnews.com">STAT</source></item>
<item><title>Healthcare AI stocks rally as nurses union meets - MarketWatch</title>
 <link>https://news.google.com/rss/articles/ccc</link><pubDate>Sun, 22 Nov 2026 08:00:00 GMT</pubDate>
 <source url="https://www.marketwatch.com">MarketWatch</source></item>
<item><title>City council approves new hospital parking - Local News</title>
 <link>https://news.google.com/rss/articles/ddd</link><pubDate>Sat, 21 Nov 2026 08:00:00 GMT</pubDate>
 <source url="https://example.com">Local News</source></item>
</channel></rss>"""

FIELD = {"zh": "医疗专业人员", "en": "Healthcare practitioners", "terms": ["radiology", "diagnosis", "nurses", "\"medical imaging\""]}


def test_parse_rss_strips_source_suffix():
    items = collect.parse_rss(RSS)
    assert len(items) == 4
    assert items[0] == {"title": "AI model reads chest X-rays as well as radiologists", "src": "Reuters",
                        "url": "https://news.google.com/rss/articles/aaa", "date": "2026-11-23"}


def test_build_query_and_url():
    q = collect.build_query(FIELD, ["AI", '"artificial intelligence"'], 14)
    assert q == '(AI OR "artificial intelligence") (radiology OR diagnosis OR nurses OR "medical imaging") when:14d'
    assert collect.rss_url(q).startswith("https://news.google.com/rss/search?q=")


def test_keyword_filter_keeps_relevant_and_classifies():
    kept = collect.keyword_filter(collect.parse_rss(RSS), FIELD, 5)
    titles = [k["en"] for k in kept]
    assert titles == ["AI model reads chest X-rays as well as radiologists", "Hospital pauses AI triage tool after diagnosis errors"]
    assert [k["k"] for k in kept] == ["signal", "check"]  # 「pauses / errors」→ 现实检验
    assert all(k["zh"] is None for k in kept)
    assert len(collect.keyword_filter(collect.parse_rss(RSS), FIELD, 1)) == 1


def test_parse_llm_validates_indices_and_kinds():
    cands = collect.parse_rss(RSS)
    content = 'Sure: {"items": [{"i": 1, "k": "check", "zh": "医院暂停 AI 分诊工具", "en": "Hospital pauses AI triage tool"},' \
              ' {"i": 1, "k": "signal"}, {"i": 99, "k": "signal"}, {"i": 0, "k": "weird", "zh": "", "en": ""}]}'
    kept = collect.parse_llm(content, cands, 5)
    assert [(k["url"][-3:], k["k"], k["zh"]) for k in kept] == [("bbb", "check", "医院暂停 AI 分诊工具"), ("aaa", "signal", None)]
    assert kept[1]["en"] == cands[0]["title"]  # 空的 en 退回原标题


def test_collect_records_failures():
    cfg = {"ai_terms": ["AI"], "fields": {"29": FIELD, "23": {"zh": "法律", "en": "Legal", "terms": ["lawyers"]}}}

    def fetcher(url):
        if "lawyers" in url:
            raise OSError("boom")
        return RSS
    new, failed = collect.collect(cfg, None, 14, 3, fetcher, collect.keyword_filter)
    assert failed == ["23"] and len(new) == 2 and all(i["fields"] == ["29"] for i in new)


def _auto(title, date, field, url=None):
    return collect.to_item({"title": title, "src": "S", "url": url or "https://x/" + title, "date": date,
                            "k": "signal", "en": title, "zh": None}, field)


def test_merge_dedupes_caps_and_expires():
    today = datetime(2026, 11, 25, tzinfo=timezone.utc)
    old = [_auto("Old story", "2026-03-01", "29"), _auto("Same story", "2026-11-20", "29")]
    new = [_auto("Same story", "2026-11-20", "19", url="https://other/same"), _auto("A", "2026-11-24", "29"),
           _auto("B", "2026-11-23", "29"), _auto("C", "2026-11-22", "29")]
    out = collect.merge(old, new, keep=3, max_age=180, today=today)
    assert [i["en"]["t"] for i in out] == ["A", "B", "C", "Same story"]
    assert out[-1]["fields"] == ["19"]  # 29 已满 3 条，只留在 19
    assert all(i["en"]["t"] != "Old story" for i in out)  # 超过 180 天


def test_main_curated_only_is_idempotent(tmp_path):
    out = tmp_path / "news.json"
    assert collect.main(["--out", str(out), "--curated-only"]) == 0
    first = out.read_text(encoding="utf-8")
    assert collect.main(["--out", str(out), "--curated-only"]) == 0
    assert out.read_text(encoding="utf-8") == first  # 没有新条目时文件不变


NEWS = ROOT / "web" / "news.json"


@pytest.mark.skipif(not NEWS.exists(), reason="news.json 还没生成")
def test_news_json_schema():
    d = json.loads(NEWS.read_text(encoding="utf-8"))
    assert d["updated"] and d["fields"]
    ids = set()
    for it in d["items"]:
        assert it["id"] not in ids
        ids.add(it["id"])
        assert it["k"] in ("signal", "check") and it["url"].startswith("http") and it["en"]["t"]
        assert it["fields"] and all(f in d["fields"] for f in it["fields"])
        assert len(it["date"]) in (7, 10)
    dates = [it["date"] for it in d["items"]]
    assert dates == sorted(dates, reverse=True)
