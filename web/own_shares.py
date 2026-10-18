"""不依赖 Hatgis-Kessell et al. 的时间占比：O*NET 频率 × 相关度 × M2 端到端时长。

O*NET 的频率问的是「多久做一次这项工作」，长任务（比如做研究）可能「每天都做」，
但一次完成要几百小时。所以每「做一次」最多算一个工作日：
    time_per_day(t) = relevance(t) × E[freq(t)] × min(hours(t), WORKDAY)
再在每个职业内部归一化成时间占比。

频率档按每个工作日的次数换算（一年按 250 个工作日）：
    1 一年一次或更少 → 0.5 次/年    2 一年多次 → 4 次/年
    3 一月多次 → 2 次/月            4 一周多次 → 2 次/周
    5 每天 → 1    6 每天多次 → 3    7 每小时或更频繁 → 8
用法：python own_shares.py --ratings "Task Ratings.xlsx" --estimates ../runs/full-v3.1/estimates.jsonl --out own_shares.csv
"""
import argparse, json
import pandas as pd

WORKDAY = 7.0
DAYS = 250
FREQ_PER_DAY = {1: 0.5 / DAYS, 2: 4 / DAYS, 3: 24 / DAYS, 4: 100 / DAYS, 5: 1.0, 6: 3.0, 7: 8.0}


def expected_freq(ratings: pd.DataFrame) -> pd.DataFrame:
    ft = ratings[ratings["Scale ID"] == "FT"].copy()
    ft["f"] = ft["Category"].astype(int).map(FREQ_PER_DAY)
    ft["p"] = ft["Data Value"] / 100
    g = ft.groupby(["O*NET-SOC Code", "Task ID"])
    ef = (g.apply(lambda x: (x.p * x.f).sum() / x.p.sum() if x.p.sum() > 0 else float("nan"), include_groups=False)
          .rename("freq_per_day").reset_index())
    rt = ratings[ratings["Scale ID"] == "RT"][["O*NET-SOC Code", "Task ID", "Data Value"]].rename(columns={"Data Value": "relevance"})
    out = ef.merge(rt, on=["O*NET-SOC Code", "Task ID"], how="outer")
    out.columns = ["onet_code", "task_id", "freq_per_day", "relevance"]
    out["task_id"] = out.task_id.astype(str)
    return out


def own_shares(est: pd.DataFrame, ef: pd.DataFrame) -> pd.DataFrame:
    d = est.merge(ef, on=["onet_code", "task_id"], how="left")
    # 没有评分的任务：用同职业的中位数补
    for c in ["freq_per_day", "relevance"]:
        d[c] = d[c].fillna(d.groupby("onet_code")[c].transform("median")).fillna(d[c].median())
    d["per_day"] = d.relevance / 100 * d.freq_per_day * d.hours.clip(upper=WORKDAY)
    d["own_share"] = d.per_day / d.groupby("onet_code").per_day.transform("sum")
    return d


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", required=True)
    ap.add_argument("--estimates", required=True)
    ap.add_argument("--out", default="own_shares.csv")
    a = ap.parse_args()
    est = pd.DataFrame([json.loads(l) for l in open(a.estimates, encoding="utf-8")])
    est["task_id"] = est.task_id.astype(str)
    ratings = pd.read_excel(a.ratings) if a.ratings.endswith("xlsx") else pd.read_csv(a.ratings, sep="\t")
    d = own_shares(est, expected_freq(ratings))
    d[["onet_code", "task_id", "hours", "task_type", "freq_per_day", "relevance", "own_share"]].to_csv(a.out, index=False)
    print(f"写入 {a.out}：{len(d)} 条任务，{d.onet_code.nunique()} 个职业")
