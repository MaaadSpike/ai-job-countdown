"""用 M3 人工标注检验 M2，并和斯坦福论文的单次时长做排序对比。

用法：
    python evaluate.py --estimates runs/v1/estimates.jsonl --labels ../m3-eval/eval_labels.csv \
        --meta ../m3-eval/eval_sample_meta.csv

指标：
- 时长：把 M2 的小时数换成和 M3 一样的 8 个档位，算完全命中率、相差 1 档以内的比例、平均差几档、二次加权 kappa
- 类型：准确率和每类的 F1
- 对照：和斯坦福 w(t,o) 的 Spearman 相关（注意它最长只到 7 小时、定义是「一天内的进展」，只看排序）
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

BIN_EDGES = [0.25, 1, 4, 8, 40, 160, 500]  # 小时；和 M3 标注页的 8 档一致


def to_bin(hours: float) -> int:
    return int(np.searchsorted(BIN_EDGES, hours, side="right")) + 1


def weighted_kappa(a, b, k=8):
    a, b = np.asarray(a, int), np.asarray(b, int)
    obs = np.zeros((k, k))
    for x, y in zip(a, b):
        obs[x - 1, y - 1] += 1
    exp = obs.sum(1, keepdims=True) @ obs.sum(0, keepdims=True) / obs.sum()
    w = np.array([[(i - j) ** 2 for j in range(k)] for i in range(k)]) / (k - 1) ** 2
    return 1 - (w * obs).sum() / (w * exp).sum()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--estimates", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True, help="agreement.py 生成的 eval_labels.csv")
    ap.add_argument("--meta", type=Path, help="eval_sample_meta.csv（斯坦福的数值）")
    args = ap.parse_args()

    est = pd.DataFrame([json.loads(l) for l in args.estimates.open(encoding="utf-8")])
    est = est[est["n_valid"] > 0]
    lab = pd.read_csv(args.labels, dtype={"task_id": str})
    lab = lab[lab["status"] == "agreed"].dropna(subset=["duration_bin", "task_type"])
    m = lab.merge(est, on="task_id", suffixes=("_human", "_model"))
    if m.empty:
        raise SystemExit("M2 结果和人工标注没有重合的任务：确认 M2 跑过 eval_tasks.jsonl")

    m["bin_model"] = m["hours"].map(to_bin)
    m["bin_human"] = m["duration_bin"].round().astype(int)
    d = (m["bin_model"] - m["duration_bin"]).abs()
    print(f"可比较的任务：{len(m)} 条\n")
    print("时长")
    print(f"  完全命中档位     {(m['bin_model'] == m['bin_human']).mean():.1%}")
    print(f"  相差 1 档以内    {(d <= 1).mean():.1%}")
    print(f"  平均差几档       {d.mean():.2f}")
    print(f"  偏向             模型平均比人工 {'高' if (m['bin_model'] - m['duration_bin']).mean() > 0 else '低'} "
          f"{abs((m['bin_model'] - m['duration_bin']).mean()):.2f} 档")
    print(f"  二次加权 kappa   {weighted_kappa(m['bin_model'], m['bin_human']):.3f}")
    print("类型")
    print(f"  准确率           {(m['task_type_model'] == m['task_type_human']).mean():.1%}")
    for t in ["digital", "physical", "trust"]:
        tp = ((m.task_type_model == t) & (m.task_type_human == t)).sum()
        p = tp / max((m.task_type_model == t).sum(), 1)
        r = tp / max((m.task_type_human == t).sum(), 1)
        f1 = 2 * p * r / max(p + r, 1e-9)
        print(f"  {t:<9} F1 {f1:.2f}（人工 {int((m.task_type_human == t).sum())} 条）")
    print("  混淆矩阵（行=人工，列=模型）：")
    print(pd.crosstab(m["task_type_human"], m["task_type_model"]).to_string())

    if args.meta and args.meta.exists():
        meta = pd.read_csv(args.meta, dtype={"task_id": str})
        mm = est.merge(meta, on=["task_id", "onet_code"])
        rho = mm["hours"].corr(mm["stanford_instance_hours"], method="spearman")
        print(f"\n与斯坦福单次时长的 Spearman 相关：{rho:.2f}（{len(mm)} 条；只比较排序）")

    worst = m.assign(diff=d).sort_values("diff", ascending=False).head(10)
    print("\n差得最多的 10 条（拿来改 prompt）：")
    for _, r in worst.iterrows():
        print(f"  人工 {r['duration_bin']:.1f} 档 · 模型 {r['bin_model']} 档（{r['hours']:.1f} h） · "
              f"{r['occupation']}：{r['task'][:70]}")


if __name__ == "__main__":
    main()
