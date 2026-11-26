"""计算两位标注者的一致性，并生成最终评测集。

用法：
    python agreement.py labels_spike.csv labels_friend.csv

输出：
    终端打印一致性指标
    disagreements.csv  需要两人一起讨论的条目（时长差 2 档及以上，或类型不同）
    eval_labels.csv    最终评测集；待讨论的条目 status=need_review，讨论完手动补上
"""
import sys
from pathlib import Path

import pandas as pd

N_BINS = 8


def weighted_kappa(a: pd.Series, b: pd.Series, k: int = N_BINS) -> float:
    """二次加权 Cohen's kappa：差得越远扣分越多，适合有序的时长档。"""
    obs = pd.crosstab(a, b).reindex(index=range(1, k + 1), columns=range(1, k + 1), fill_value=0).to_numpy(float)
    n = obs.sum()
    if n == 0:
        return float("nan")
    exp = obs.sum(1, keepdims=True) @ obs.sum(0, keepdims=True) / n
    w = [[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)]
    num = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k))
    den = sum(w[i][j] * exp[i][j] for i in range(k) for j in range(k))
    return 1 - num / den if den else float("nan")


def cohen_kappa(a: pd.Series, b: pd.Series) -> float:
    po = (a == b).mean()
    cats = sorted(set(a) | set(b))
    pe = sum((a == c).mean() * (b == c).mean() for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def main(path_a: str, path_b: str):
    a = pd.read_csv(path_a, dtype={"task_id": str})
    b = pd.read_csv(path_b, dtype={"task_id": str})
    for path, df in ((path_a, a), (path_b, b)):
        if df.empty:
            sys.exit(f"{path} 里没有任何标注，先确认它已经标完")
    name_a, name_b = a["annotator"].iloc[0], b["annotator"].iloc[0]
    m = a.merge(b, on="task_id", suffixes=("_a", "_b"))

    both = m[(m["skipped_a"] == 0) & (m["skipped_b"] == 0)].copy()
    both["duration_bin_a"] = both["duration_bin_a"].astype(int)
    both["duration_bin_b"] = both["duration_bin_b"].astype(int)
    diff = (both["duration_bin_a"] - both["duration_bin_b"]).abs()
    type_agree = both["task_type_a"] == both["task_type_b"]

    print(f"{name_a} 标了 {len(a)} 条，{name_b} 标了 {len(b)} 条，共同标注 {len(m)} 条，"
          f"两人都没跳过 {len(both)} 条\n")
    print("时长档")
    print(f"  二次加权 kappa   {weighted_kappa(both['duration_bin_a'], both['duration_bin_b']):.3f}")
    print(f"  Spearman 相关    {both['duration_bin_a'].corr(both['duration_bin_b'], method='spearman'):.3f}")
    print(f"  完全一致         {(diff == 0).mean():.1%}")
    print(f"  相差 1 档以内    {(diff <= 1).mean():.1%}")
    print("任务类型（数字 / 物理操作 / 人际信任）")
    print(f"  Cohen's kappa    {cohen_kappa(both['task_type_a'], both['task_type_b']):.3f}")
    print(f"  一致率           {type_agree.mean():.1%}")
    print("  两人的类型交叉表：")
    print(pd.crosstab(both["task_type_a"], both["task_type_b"], rownames=[name_a], colnames=[name_b]).to_string())
    print("\n参考：kappa 0.6 以上算较好，0.4 以下说明标注说明需要改。")

    both["duration_diff"] = diff
    both["type_agree"] = type_agree
    need = (both["duration_diff"] >= 2) | (~both["type_agree"])
    review = both[need]
    sample_path = Path("eval_sample.csv")
    if sample_path.exists():
        sample = pd.read_csv(sample_path, dtype={"task_id": str})[["task_id", "item_no", "occupation", "task"]]
        review = sample.merge(review, on="task_id")
    review.to_csv("disagreements.csv", index=False, encoding="utf-8-sig")
    print(f"\n{len(review)} 条需要讨论，已写入 disagreements.csv")

    out = both[["task_id"]].copy()
    out["duration_bin"] = (both["duration_bin_a"] + both["duration_bin_b"]) / 2
    out["task_type"] = both["task_type_a"]
    out["status"] = "agreed"
    out.loc[need.values, ["duration_bin", "task_type"]] = None
    out.loc[need.values, "status"] = "need_review"
    out.to_csv("eval_labels.csv", index=False, encoding="utf-8-sig")
    print(f"eval_labels.csv：{int((out['status'] == 'agreed').sum())} 条已定，"
          f"{int(need.sum())} 条讨论后手动补上")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("用法：python agreement.py labels_A.csv labels_B.csv")
    main(sys.argv[1], sys.argv[2])
