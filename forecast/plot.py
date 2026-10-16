"""画 80% 可靠度 time horizon 的前沿点和两种窗口下的随机游走预测带（10%–90%）。"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from scipy import stats

import analysis as A

for f in ["Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Zen Hei", "Source Han Sans SC"]:
    if any(f in x.name for x in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False

SURFACE, INK, INK2, GRID = "#fcfcfb", "#1f1f1e", "#5f5e5a", "#e6e5e0"
C_RECENT, C_ALL = "#2a78d6", "#eb6834"

pts = A.series("p80")
hold = [(A.yr(d), np.log2(p80), n) for n, d, p50, p80 in A.HOLDOUT]
fr_all = A.frontier(pts + hold)

fig, ax = plt.subplots(figsize=(10, 6.2), dpi=160)
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)

t_end = A.yr("2028-12-31")
for window, color, label in ((2.0, C_RECENT, "按最近 2 年的趋势"), (None, C_ALL, "按 2019 年以来的全部趋势")):
    fr = fr_all if window is None else [p for p in fr_all if p[0] >= fr_all[-1][0] - window]
    m = A.RandomWalk().fit([p[0] for p in fr], [p[1] for p in fr])
    ts = np.linspace(m.t_last, t_end, 200)
    mu = np.array([m.predict(t)[0] for t in ts])
    se = np.array([m.predict(t)[1] for t in ts])
    q = stats.t.ppf(0.9, m.df)
    ax.fill_between(ts, mu - q * se, mu + q * se, color=color, alpha=0.13, lw=0)
    ax.plot(ts, mu, color=color, lw=2)
    ax.text(t_end + 0.05, mu[-1], f"{label}\n每 {m.doubling_days:.0f} 天翻倍", color=INK, va="center", fontsize=9.5)
    ax.plot([t_end + 0.0, t_end + 0.04], [mu[-1], mu[-1]], color=color, lw=2)

all_t = [p[0] for p in pts + hold]
all_y = [p[1] for p in pts + hold]
fr_names = {p[2] for p in fr_all}
for t, y, n in pts + hold:
    on = n in fr_names
    held = any(n == h[2] for h in hold)
    ax.scatter(t, y, s=46 if on else 22, zorder=5,
               facecolor=(INK if on else "#b4b2a9") if not held else SURFACE,
               edgecolor=INK if (on or held) else "#b4b2a9", linewidth=1.4 if held else 0.5)
for name, dx, dy, ha in [("GPT-4", 0.0, 0.9, "center"), ("o1", -0.05, 0.6, "right"),
                         ("Claude Mythos Preview (early)", -0.06, 0.5, "right")]:
    t, y, _ = next(p for p in pts + hold if p[2] == name)
    ax.text(t + dx, y + dy, name, fontsize=8.5, color=INK2, ha=ha)

today = A.yr("2026-10-14")
ax.axvline(today, color=INK2, lw=0.8, ls=(0, (3, 3)))
ax.text(today + 0.04, np.log2(0.3), "今天", fontsize=9, color=INK2)

ticks = [(1 / 60, "1 秒"), (1, "1 分钟"), (10, "10 分钟"), (60, "1 小时"), (8 * 60, "8 小时"),
         (40 * 60, "40 小时\n（一周）"), (167 * 60, "167 小时\n（一个月）"), (2000 * 60, "2000 小时\n（一年）"), (10000 * 60, "10000 小时")]
ax.set_yticks([np.log2(v) for v, _ in ticks], [l for _, l in ticks])
ax.set_ylim(np.log2(0.005), np.log2(12000 * 60))
years = list(range(2019, 2030))
ax.set_xticks([A.yr(f"{y}-01-01") for y in years], [str(y) for y in years])
ax.set_xlim(A.yr("2019-01-01"), t_end + 0.95)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
for s in ("left", "bottom"):
    ax.spines[s].set_color(GRID)
ax.grid(axis="y", color=GRID, lw=0.8)
ax.tick_params(colors=INK2, labelsize=9, length=0)
ax.set_ylabel("AI 能以 80% 成功率完成的任务长度（按人类耗时）", color=INK2, fontsize=9.5)
ax.set_title("按最近两年还是全部历史外推，「一个月长的任务」相差一年多", loc="left", color=INK, fontsize=12.5, pad=24)
ax.text(0, 1.015, "实心点：刷新纪录的模型 · 灰点：未破纪录 · 空心点：2026-03 之后公布（样本外检验用，预测带已纳入） · 色带：80% 预测区间",
        transform=ax.transAxes, fontsize=8.5, color=INK2)
fig.text(0.01, 0.01, "数据：METR Time Horizon 1.1（2023 年起）与 1.0（2019–2022，按 METR 原始数据复现）。模型：带漂移的随机游走（Farmer & Lafond 2016）。",
         fontsize=7.5, color=INK2)
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig("horizon_forecast_p80.png", facecolor=SURFACE)
print("saved")
