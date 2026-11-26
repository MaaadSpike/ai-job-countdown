"""检查：网站用的任务清单能不能只靠 O*NET 重建，不依赖 Hatgis-Kessell et al. 的 xlsx。

比较 M2 估计过的任务（runs/.../estimates.jsonl）和 O*NET 30.2 Task Ratings.xlsx 里有评分的任务：
- 每条估计过的任务是否都在 O*NET 里（同一个职业代码 + Task ID）
- 任务原文是否和 O*NET 一致
- O*NET 里有评分、但还没估计过的任务有多少（换成 O*NET 清单后需要补估的数量）

用法（在仓库根目录）：
    python estimate/check_onet_subset.py
    python estimate/check_onet_subset.py --ratings "data/Task Ratings.xlsx" --estimates runs/full-v3.1/estimates.jsonl
"""
import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def onet_rated_tasks(ratings: pd.DataFrame) -> pd.DataFrame:
    """有频率（FT）和相关度（RT）评分的任务：网站时间占比公式需要这两个评分。"""
    r = ratings.rename(columns={"O*NET-SOC Code": "onet_code", "Task ID": "task_id", "Title": "occupation", "Task": "task"})
    r["task_id"] = r["task_id"].astype(str)
    has = r.groupby(["onet_code", "task_id"])["Scale ID"].agg(set)
    rated = has[has.apply(lambda s: {"FT", "RT"} <= s)].index
    t = r.drop_duplicates(["onet_code", "task_id"]).set_index(["onet_code", "task_id"])
    return t.loc[rated, ["occupation", "task"]].reset_index()


def compare(est: pd.DataFrame, onet: pd.DataFrame) -> dict:
    est = est.assign(task_id=est["task_id"].astype(str))
    m = est.merge(onet, on=["onet_code", "task_id"], how="left", suffixes=("", "_onet"), indicator=True)
    found = m["_merge"] == "both"
    same_text = found & (m["task"].map(norm) == m["task_onet"].map(norm))
    k_est = set(zip(est.onet_code, est.task_id))
    k_onet = set(zip(onet.onet_code, onet.task_id))
    return {
        "estimated": len(k_est),
        "in_onet": int(found.sum()),
        "same_text": int(same_text.sum()),
        "missing_from_onet": sorted(k_est - k_onet)[:10],
        "n_missing_from_onet": len(k_est - k_onet),
        "onet_rated": len(k_onet),
        "onet_not_estimated": len(k_onet - k_est),
        "onet_occ_not_estimated": len({c for c, _ in k_onet} - {c for c, _ in k_est}),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="任务清单能否只靠 O*NET 重建")
    ap.add_argument("--ratings", default=str(ROOT / "data" / "Task Ratings.xlsx"))
    ap.add_argument("--estimates", default=str(ROOT / "runs" / "full-v3.1" / "estimates.jsonl"))
    a = ap.parse_args(argv)

    ratings = pd.read_excel(a.ratings) if a.ratings.endswith("xlsx") else pd.read_csv(a.ratings, sep="\t")
    est = pd.DataFrame([json.loads(x) for x in open(a.estimates, encoding="utf-8") if x.strip()])
    r = compare(est, onet_rated_tasks(ratings))

    print(f"估计过的任务：{r['estimated']}")
    print(f"  在 O*NET 有评分的任务里找到：{r['in_onet']}（原文完全一致 {r['same_text']}）")
    if r["n_missing_from_onet"]:
        print(f"  O*NET 里找不到：{r['n_missing_from_onet']}，例如 {r['missing_from_onet']}")
    print(f"O*NET 有评分的任务：{r['onet_rated']}，其中还没估计过 {r['onet_not_estimated']}"
          f"（涉及 {r['onet_occ_not_estimated']} 个完全没估计过的职业）")
    ok = r["n_missing_from_onet"] == 0 and r["same_text"] == r["estimated"]
    print("\n结论：" + ("网站用到的每条任务都能直接从 O*NET 拿到，原文一致。任务清单可以写成「来自 O*NET 30.2」，"
                    "不再需要 Hatgis-Kessell 的 xlsx。" if ok else
                    "有任务在 O*NET 里找不到或原文不一致，先看上面列出的例子。"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
