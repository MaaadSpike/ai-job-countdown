"""从 O*NET 任务里分层抽样，生成 M3 评测集的待标注清单。

用法（不用自己下载 O*NET）：
    python sample_tasks.py --time-shares task_time_share_estimates.xlsx

task_time_share_estimates.xlsx 来自 Hatgis-Kessell et al. (2026) 的公开仓库：
    https://github.com/Stephanehk/Estimating-Time-Spent-On-Work
它基于 O*NET 30.2，覆盖 876 个职业的 17,525 条任务，自带任务描述和职业名称。
可选：--occupation-data occupation_data.csv（O*NET 职业描述，用来在标注页显示「这个职业是做什么的」）

抽样规则：
- 只抽有时间占比估计的任务
- 按 SOC 大类（职业编号前两位）均匀分配名额
- 每个大类里先抽职业、每个职业只抽 1 条任务，职业不够时才补第 2 条
- 前 20 条标为试标集（calibration=1），横跨尽量多的大类

输出两个文件：
- eval_sample.csv       给标注页用，只有任务和职业信息
- eval_sample_meta.csv  斯坦福的时长和时间占比，留着之后对比；标注时不要打开，以免影响判断
"""
import argparse
from pathlib import Path

import pandas as pd

MAJOR_GROUPS = {
    "11": "管理", "13": "商业与金融", "15": "计算机与数学", "17": "建筑与工程",
    "19": "生命、物理与社会科学", "21": "社区与社会服务", "23": "法律", "25": "教育与图书馆",
    "27": "艺术、设计、娱乐、体育与媒体", "29": "医疗从业者与技术人员", "31": "医疗辅助",
    "33": "保护性服务", "35": "餐饮", "37": "楼宇与场地清洁维护", "39": "个人护理与服务",
    "41": "销售", "43": "办公与行政支持", "45": "农林渔", "47": "建造与采掘",
    "49": "安装、维护与维修", "51": "生产", "53": "交通与物流", "55": "军事",
}


def load(path: Path, occ_path: Path | None) -> pd.DataFrame:
    d = pd.read_excel(path, dtype={"Task ID": str, "Occupation ID": str})
    d = d.rename(columns={
        "Task ID": "task_id", "Task Name": "task", "Occupation ID": "onet_code", "Occupation Name": "occupation",
        "Time spent per day estimate (w(t,o) · E[f(t,o)])": "stanford_hours_per_day",
        "Time per single instance (w(t,o))": "stanford_instance_hours",
        "Expected daily frequency (E[f(t,o)])": "stanford_daily_freq",
    })
    d["stanford_time_share"] = d["stanford_hours_per_day"] / d.groupby("onet_code")["stanford_hours_per_day"].transform("sum")
    d["major_group"] = d["onet_code"].str[:2]
    d["major_group_name"] = d["major_group"].map(MAJOR_GROUPS).fillna("其他")
    d["occupation_description"] = ""
    if occ_path and occ_path.exists():
        occ = pd.read_csv(occ_path, dtype=str)
        occ.columns = [c.strip() for c in occ.columns]
        desc = dict(zip(occ["O*NET-SOC Code"], occ["Description"]))
        d["occupation_description"] = d["onet_code"].map(desc).fillna("")
    return d


def allocate(groups: pd.Series, n: int) -> dict:
    sizes = groups.value_counts().to_dict()
    quota = {g: 0 for g in sizes}
    remaining = n
    while remaining > 0:
        open_groups = [g for g in sizes if quota[g] < sizes[g]]
        if not open_groups:
            break
        share = max(1, remaining // len(open_groups))
        for g in sorted(open_groups, key=lambda g: -sizes[g]):
            take = min(share, sizes[g] - quota[g], remaining)
            quota[g] += take
            remaining -= take
            if remaining == 0:
                break
    return quota


def sample_group(g: pd.DataFrame, k: int, seed: int) -> pd.DataFrame:
    one_per_occ = g.groupby("onet_code", group_keys=False).sample(n=1, random_state=seed)
    if len(one_per_occ) >= k:
        return one_per_occ.sample(n=k, random_state=seed)
    rest = g.drop(one_per_occ.index)
    extra = rest.sample(n=min(k - len(one_per_occ), len(rest)), random_state=seed)
    return pd.concat([one_per_occ, extra])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-shares", type=Path, default=Path("task_time_share_estimates.xlsx"))
    ap.add_argument("--occupation-data", type=Path, default=Path("occupation_data.csv"))
    ap.add_argument("--out", type=Path, default=Path("eval_sample.csv"))
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--n-calibration", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20261014)
    args = ap.parse_args()

    df = load(args.time_shares, args.occupation_data)
    quota = allocate(df["major_group"], args.n)
    parts = [sample_group(df[df["major_group"] == g], k, args.seed) for g, k in quota.items() if k > 0]
    sample = pd.concat(parts).reset_index(drop=True)

    sample = sample.sample(frac=1, random_state=args.seed).reset_index(drop=True)
    sample["rank_in_group"] = sample.groupby("major_group").cumcount()
    sample = sample.sort_values(["rank_in_group", "major_group"]).reset_index(drop=True)
    sample["calibration"] = (sample.index < args.n_calibration).astype(int)
    calib = sample[sample["calibration"] == 1]
    rest = sample[sample["calibration"] == 0].sample(frac=1, random_state=args.seed + 1)
    sample = pd.concat([calib, rest]).reset_index(drop=True)
    sample.insert(0, "item_no", range(1, len(sample) + 1))

    cols = ["item_no", "calibration", "task_id", "onet_code", "occupation", "major_group",
            "major_group_name", "task", "occupation_description"]
    sample[cols].to_csv(args.out, index=False, encoding="utf-8-sig")
    meta = ["item_no", "task_id", "onet_code", "stanford_instance_hours", "stanford_daily_freq",
            "stanford_hours_per_day", "stanford_time_share"]
    sample[meta].to_csv(args.out.with_name(args.out.stem + "_meta.csv"), index=False, encoding="utf-8-sig")

    print(f"写入 {args.out}：共 {len(sample)} 条，其中试标 {int(sample['calibration'].sum())} 条")
    print(f"覆盖 {sample['major_group'].nunique()} 个大类、{sample['onet_code'].nunique()} 个职业")


if __name__ == "__main__":
    main()
