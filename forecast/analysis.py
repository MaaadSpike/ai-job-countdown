"""METR time horizon 趋势：两种外推模型 + walk-forward 回测 + 带误差带的预测。

数据来源
- 2019–2022（GPT-2 / GPT-3 / GPT-3.5）：用 METR 公开的原始运行数据（github.com/METR/eval-analysis-public，
  reports/time-horizon-1-0/data/raw/runs.jsonl）和 METR 自己的 logistic 拟合代码复现，与 METR 的拼接做法一致
- 2023 年起：METR 公布的 Time Horizon 1.1 数值（Wikipedia「METR」条目转录的 METR 表格）
- 2026-03 之后的 3 个模型不在 GitHub 数据里，只作样本外检验，不参与回测拟合

模型
- OLS 趋势：log2(horizon) 对发布日期做线性回归（METR 的做法），给 t 分布预测区间
- 带漂移的随机游走（Farmer & Lafond 2016）：漂移 = 首尾斜率；噪声方差按时间间隔归一；
  预测方差 = sigma^2 * (tau + tau^2 / T)，第二项是漂移估计误差
两种模型都只用「前沿」模型：发布时刷新了纪录的那些。
"""
import json
from datetime import date

import numpy as np
from scipy import stats

MIN = 1.0
SEC = 1 / 60

# name, release date, p50 (minutes), p80 (minutes), source
DATA = [
    ("GPT-2", "2019-02-14", 0.0538, 0.0128, "TH1.0 复现"),
    ("GPT-3 (davinci-002)", "2020-05-28", 0.1441, 0.0562, "TH1.0 复现"),
    ("GPT-3.5 (instruct)", "2022-03-15", 0.5992, 0.2554, "TH1.0 复现"),
    ("GPT-4", "2023-03-14", 4, 37 * SEC, "TH1.1"),
    ("GPT-4 1106", "2023-11-06", 4, 34 * SEC, "TH1.1"),
    ("Claude 3 Opus", "2024-03-04", 4, 29 * SEC, "TH1.1"),
    ("GPT-4 Turbo", "2024-04-09", 3, 37 * SEC, "TH1.1"),
    ("GPT-4o", "2024-05-13", 6, 57 * SEC, "TH1.1"),
    ("Claude 3.5 Sonnet (Old)", "2024-06-20", 11, 1, "TH1.1"),
    ("o1-preview", "2024-09-12", 19, 3, "TH1.1"),
    ("Claude 3.5 Sonnet (New)", "2024-10-22", 20, 2, "TH1.1"),
    ("o1", "2024-12-05", 38, 6, "TH1.1"),
    ("Claude 3.7 Sonnet", "2025-02-24", 60, 10, "TH1.1"),
    ("o3", "2025-04-16", 121, 24, "TH1.1"),
    ("Claude Opus 4", "2025-05-22", 101, 17, "TH1.1"),
    ("Claude Opus 4.1", "2025-08-05", 101, 19, "TH1.1"),
    ("GPT-5", "2025-08-07", 214, 32, "TH1.1"),
    ("Gemini 3 Pro", "2025-11-18", 237, 43, "TH1.1"),
    ("GPT-5.1-Codex-Max", "2025-11-19", 237, 41, "TH1.1"),
    ("Claude Opus 4.5", "2025-11-24", 320, 42, "TH1.1"),
    ("GPT-5.2", "2025-12-11", 394, 55, "TH1.1"),
    ("Claude Opus 4.6", "2026-02-05", 719, 70, "TH1.1"),
    ("GPT-5.3-Codex", "2026-02-05", 390, 47, "TH1.1"),
]
# 样本外：METR 2026-03 之后公布；发布日期只知道月份，取月中
HOLDOUT = [
    ("Gemini 3.1 Pro", "2026-03-15", 350, 90),
    ("GPT-5.4", "2026-03-15", 342, 54),
    ("Claude Mythos Preview (early)", "2026-04-15", None, 186),  # p50 只知道「至少 16 小时」
]
MYTHOS_P50_LOWER = 16 * 60

EPOCH = date(2019, 1, 1)


def yr(d: str) -> float:
    return (date.fromisoformat(d) - EPOCH).days / 365.25


def to_date(t: float) -> date:
    return date.fromordinal(EPOCH.toordinal() + int(round(t * 365.25)))


def frontier(points):
    """按发布日期排序，只保留刷新纪录的模型。同一天发布的取较高者。"""
    pts = sorted(points, key=lambda p: (p[0], -p[1]))
    out, best = [], -np.inf
    for t, y, name in pts:
        if y > best:
            out.append((t, y, name))
            best = y
    return out


class OLS:
    name = "OLS 趋势"

    def fit(self, t, y):
        self.t, self.y = np.asarray(t), np.asarray(y)
        n = len(t)
        self.b, self.a = np.polyfit(self.t, self.y, 1)
        resid = self.y - (self.a + self.b * self.t)
        self.s = np.sqrt(resid @ resid / (n - 2))
        self.df = n - 2
        self.tbar, self.sxx = self.t.mean(), ((self.t - self.t.mean()) ** 2).sum()
        return self

    def predict(self, t0):
        mu = self.a + self.b * t0
        se = self.s * np.sqrt(1 + 1 / len(self.t) + (t0 - self.tbar) ** 2 / self.sxx)
        return mu, se, self.df

    @property
    def doubling_days(self):
        return 365.25 / self.b


class RandomWalk:
    name = "随机游走+漂移"

    def fit(self, t, y):
        t, y = np.asarray(t), np.asarray(y)
        self.t_last, self.y_last = t[-1], y[-1]
        self.T = t[-1] - t[0]
        dt, dy = np.diff(t), np.diff(y)
        keep = dt > 1e-6
        dt, dy = dt[keep], dy[keep]
        self.mu = (y[-1] - y[0]) / self.T
        z = (dy - self.mu * dt) / np.sqrt(dt)
        self.sigma = np.sqrt(z @ z / max(len(z) - 1, 1))
        self.df = max(len(z) - 1, 1)
        return self

    def predict(self, t0):
        tau = max(t0 - self.t_last, 0.0)
        mu = self.y_last + self.mu * tau
        se = self.sigma * np.sqrt(tau + tau ** 2 / self.T) if tau > 0 else 1e-9
        return mu, se, self.df

    @property
    def doubling_days(self):
        return 365.25 / self.mu


def series(which):
    idx = 2 if which == "p50" else 3
    return [(yr(d[1]), np.log2(d[idx]), d[0]) for d in DATA]


def backtest(which, window_years=None, start="2023-03-01", level=0.8):
    """每个前沿模型发布那天当截止点：只用截止点之前（含）的前沿数据拟合，预测之后每个前沿模型。"""
    pts = series(which)
    fr_all = frontier(pts)
    rows = []
    for k, (tc, _, cname) in enumerate(fr_all):
        if tc < yr(start):
            continue
        avail = [p for p in pts if p[0] <= tc]
        fr = frontier(avail)
        if window_years is not None:
            fr = [p for p in fr if p[0] >= tc - window_years]
        if len(fr) < 4:
            continue
        t, y = [p[0] for p in fr], [p[1] for p in fr]
        targets = [p for p in fr_all if p[0] > tc + 1e-9]
        for Model in (OLS, RandomWalk):
            m = Model().fit(t, y)
            for tt, yt, tname in targets:
                mu, se, df = m.predict(tt)
                q = stats.t.ppf(0.5 + level / 2, df)
                rows.append(dict(model=m.name, cutoff=cname, target=tname, lead=tt - tc,
                                 err=yt - mu, z=(yt - mu) / se, covered=abs(yt - mu) <= q * se))
    return rows


def summarize(rows, label):
    out = []
    buckets = [(0, 0.5, "0–6 个月"), (0.5, 1.0, "6–12 个月"), (1.0, 3.5, "12 个月以上")]
    for model in ("OLS 趋势", "随机游走+漂移"):
        for lo, hi, bl in buckets:
            r = [x for x in rows if x["model"] == model and lo <= x["lead"] < hi]
            if not r:
                continue
            err = np.array([x["err"] for x in r])
            out.append(dict(setting=label, model=model, lead=bl, n=len(r),
                            mae_doublings=float(np.mean(np.abs(err))),
                            bias_doublings=float(np.mean(err)),
                            mae_factor=float(2 ** np.mean(np.abs(err))),
                            coverage80=float(np.mean([x["covered"] for x in r]))))
    return out


def holdout_check(which):
    """用 2026-02 之前的全部前沿数据拟合，预测 2026-03 之后公布的模型。"""
    pts = series(which)
    record = 2 ** max(p[1] for p in pts)
    res = {}
    for window, wl in ((None, "全部历史"), (2.0, "最近 2 年")):
        fr = frontier(pts)
        if window:
            fr = [p for p in fr if p[0] >= fr[-1][0] - window]
        t, y = [p[0] for p in fr], [p[1] for p in fr]
        for Model in (OLS, RandomWalk):
            m = Model().fit(t, y)
            for name, d, p50, p80 in HOLDOUT:
                actual = p50 if which == "p50" else p80
                mu, se, df = m.predict(yr(d))
                q = stats.t.ppf(0.9, df)
                res.setdefault(name, []).append(dict(
                    setting=f"{wl} · {m.name}", pred_min=2 ** mu, lo80=2 ** (mu - q * se), hi80=2 ** (mu + q * se),
                    actual=actual, lower_bound=MYTHOS_P50_LOWER if (which == "p50" and actual is None) else None,
                    sets_record=(actual or MYTHOS_P50_LOWER) > record))
    return res


def crossing_dates(which, task_hours, window_years=2.0, n_sims=20000, seed=0, include_holdout=True):
    """随机游走模拟：AI 的 horizon 第一次达到某个任务时长的日期分布（中位数和 10%/90% 分位）。"""
    pts = series(which)
    if include_holdout:
        for name, d, p50, p80 in HOLDOUT:
            v = p50 if which == "p50" else p80
            if v is not None:
                pts.append((yr(d), np.log2(v), name))
    fr = frontier(pts)
    if window_years:
        fr = [p for p in fr if p[0] >= fr[-1][0] - window_years]
    t, y = np.array([p[0] for p in fr]), np.array([p[1] for p in fr])
    m = RandomWalk().fit(t, y)
    rng = np.random.default_rng(seed)
    step = 1 / 52
    horizon_years = 15
    n_steps = int(horizon_years / step)
    drift_se = m.sigma / np.sqrt(m.T)
    drifts = m.mu + drift_se * rng.standard_t(m.df, n_sims)
    shocks = m.sigma * np.sqrt(step) * rng.standard_normal((n_sims, n_steps))
    paths = m.y_last + np.cumsum(drifts[:, None] * step + shocks, axis=1)
    out = {}
    for h in task_hours:
        target = np.log2(h * 60)
        hit = paths >= target
        first = np.where(hit.any(axis=1), hit.argmax(axis=1), n_steps)
        when = m.t_last + (first + 1) * step
        when = np.where(target <= m.y_last, m.t_last, when)
        q10, q50, q90 = np.quantile(when, [0.1, 0.5, 0.9])
        out[h] = (to_date(q10), to_date(q50), to_date(q90))
    return m, fr, out


def main():
    report = {}
    print("=" * 70)
    for which in ("p50", "p80"):
        fr = frontier(series(which))
        t, y = [p[0] for p in fr], [p[1] for p in fr]
        full = OLS().fit(t, y)
        recent = [p for p in fr if p[0] >= yr("2023-01-01")]
        r23 = OLS().fit([p[0] for p in recent], [p[1] for p in recent])
        print(f"[{which}] 前沿模型 {len(fr)} 个：{', '.join(p[2] for p in fr)}")
        print(f"  翻倍时间：全时段 {full.doubling_days:.0f} 天，2023 年起 {r23.doubling_days:.0f} 天")
        report[f"{which}_doubling_full_days"] = full.doubling_days
        report[f"{which}_doubling_2023_days"] = r23.doubling_days

    print("\n回测（walk-forward，80% 预测区间覆盖率应接近 80%）")
    all_summ = []
    for which in ("p50", "p80"):
        for window, wl in ((None, "全部历史"), (2.0, "最近 2 年")):
            rows = backtest(which, window)
            all_summ += summarize(rows, f"{which} · {wl}")
    for s in all_summ:
        print(f"  {s['setting']:<14} {s['model']:<8} {s['lead']:<8} n={s['n']:<3} "
              f"平均误差 {s['mae_doublings']:.2f} 次翻倍（{s['mae_factor']:.1f} 倍） "
              f"偏差 {s['bias_doublings']:+.2f}  覆盖率 {s['coverage80']:.0%}")
    report["backtest"] = all_summ

    print("\n样本外检验（只用 2026-02 之前的数据）")
    ho = {}
    for which in ("p50", "p80"):
        res = holdout_check(which)
        ho[which] = res
        for name, lst in res.items():
            for r in lst:
                act = r["actual"]
                act_s = f"{act:.0f}" if act else f"≥{r['lower_bound']:.0f}"
                if not r["sets_record"]:
                    continue
                inside = (r["lo80"] <= act <= r["hi80"]) if act else (r["hi80"] >= r["lower_bound"])
                print(f"  [{which}] {name:<30} {r['setting']:<18} 预测 {r['pred_min']:6.0f} 分钟 "
                      f"[{r['lo80']:.0f}, {r['hi80']:.0f}]  实际 {act_s}  {'在区间内' if inside else '区间外'}")
        skipped = [n for n, lst in res.items() if not lst[0]["sets_record"]]
        if skipped:
            print(f"  [{which}] 没破纪录、不计分（趋势线预测的是前沿纪录）：{', '.join(skipped)}")
    report["holdout"] = ho

    report["crossing_p80"] = {}
    for window, wl in ((2.0, "最近 2 年"), (None, "全部历史")):
        print(f"\n80% 可靠度下，AI horizon 达到某个任务时长的日期（随机游走 · {wl}窗口 · 含样本外数据）")
        m, fr, out = crossing_dates("p80", [1, 2, 4, 8, 16, 40, 160], window_years=window)
        print(f"  起点：{fr[-1][2]}，{2 ** fr[-1][1]:.0f} 分钟；翻倍 {m.doubling_days:.0f} 天；sigma {m.sigma:.2f}")
        for h, (a, b, c) in out.items():
            print(f"  {h:>4} 小时：中位数 {b}，80% 区间 {a} 到 {c}")
        report["crossing_p80"][wl] = dict(doubling_days=m.doubling_days, sigma=m.sigma,
                                          dates={h: [str(x) for x in v] for h, v in out.items()})
    json.dump(report, open("report.json", "w"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
