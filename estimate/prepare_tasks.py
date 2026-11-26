"""把任务表转成 M2 的输入 tasks.jsonl。

默认读取 Hatgis-Kessell et al. (2026) 公开的 task_time_share_estimates.xlsx（O*NET 30.2，17,525 条任务），
这样 M2 的任务范围和时间占比数据完全对得上：
    https://github.com/Stephanehk/Estimating-Time-Spent-On-Work

用法：
    python prepare_tasks.py --xlsx task_time_share_estimates.xlsx --out tasks.jsonl
    python prepare_tasks.py --xlsx task_time_share_estimates.xlsx --only ../m3-eval/eval_sample.csv --out eval_tasks.jsonl
"""
import argparse
import json
from pathlib import Path

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", type=Path, default=Path("task_time_share_estimates.xlsx"))
    ap.add_argument("--onet-ratings", type=Path,
                    help="改从 O*NET 30.2 的 Task Ratings.xlsx 取任务（有频率和相关度评分的任务），不用 --xlsx")
    ap.add_argument("--out", type=Path, default=Path("tasks.jsonl"))
    ap.add_argument("--only", type=Path, help="只保留这个 CSV 里出现的 task_id（例如 M3 的 eval_sample.csv）")
    args = ap.parse_args()

    if args.onet_ratings:
        from check_onet_subset import onet_rated_tasks
        p = str(args.onet_ratings)
        ratings = pd.read_excel(p) if p.endswith("xlsx") else pd.read_csv(p, sep="\t")
        d = onet_rated_tasks(ratings)[["task_id", "onet_code", "occupation", "task"]]
    else:
        d = pd.read_excel(args.xlsx, dtype={"Task ID": str, "Occupation ID": str})
        d = d.rename(columns={"Task ID": "task_id", "Task Name": "task", "Occupation ID": "onet_code",
                              "Occupation Name": "occupation"})
        d = d[["task_id", "onet_code", "occupation", "task"]].drop_duplicates(["task_id", "onet_code"])
    if args.only:
        keep = set(pd.read_csv(args.only, dtype={"task_id": str})["task_id"])
        d = d[d["task_id"].isin(keep)]
    with args.out.open("w", encoding="utf-8") as f:
        for r in d.to_dict("records"):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"写入 {args.out}：{len(d)} 条任务，{d['onet_code'].nunique()} 个职业")


if __name__ == "__main__":
    main()
