# AI 工作倒计时

[English](README.md) | **中文**

输入一个职业，看看如果 AI 的能力按测得的速度继续增长，AI agent 什么时候能独立完成这个职业一半的工作时间。

做法是把每个职业拆成 O\*NET 里的具体任务，估计熟练从业者做一次每项任务要多久，再套上 [METR](https://metr.org) 测得的 AI agent 时间跨度（time horizon）增长曲线。

> 进行中的研究项目。倒计时是基于明确假设的推算，不是预测。AI 能做某项任务，不等于会取代做这项任务的人。

完整设计文档：[docs/DESIGN.zh-CN.md](docs/DESIGN.zh-CN.md)（[English](docs/DESIGN.md)）。

## 怎么算的

```
O*NET 30.2 任务清单 ─┬─► estimate/（vLLM 上的 Qwen2.5-32B）─► 单次时长 + 任务类型
                     │                                             │
                     │       annotate/（人工标注）──► 检验 ─────────┘
                     │                                             │
O*NET 任务评分 ──────┴─► web/own_shares.py ─► 工作时间占比 ◄────────┘
                                                    │
METR 时间跨度趋势（forecast/）──────────────────────┤
                                                    ▼
                             web/build_data.py ─► web/occupations.json ─► web/index.html
```

每项任务要等多久 AI 才能做到：

```
等待月数 = 翻倍周期 × log2(任务时长 × 难度折扣 ÷ 当前时间跨度)
```

把任务按等待时间排序，依次累加它们的工作时间占比，加到设定的比例（默认 50%）时就是「能力到位」，再加上落地期就是「实际落地」。

## 数据策略

| 数据 | 来源 | 说明 |
|---|---|---|
| 任务和职业 | [O\*NET 30.2](https://www.onetcenter.org)（CC BY 4.0） | 876 个职业、17,525 项任务。第一期用的任务子集和 Hatgis-Kessell et al. (2026) 相同。 |
| 每项任务做一次要多久 | **自己估计**：vLLM 上的 Qwen2.5-32B-Instruct-AWQ（`estimate/`） | 熟练从业者、端到端、不用 AI；每项采样 5 次取中位数 |
| 任务类型 | 同一次模型运行 | 电脑可完成、依赖人际信任、需要现场操作 |
| 工作时间占比 | **自己的公式**（`web/own_shares.py`） | O\*NET 执行频率 × O\*NET 相关度 × min(单次时长, 7 小时)，在职业内部归一化 |
| AI 能力 | METR Time Horizon 1.1 | 80% 可靠度约 3.1 小时，50% 可靠度约 16 小时；按拟合时段不同，翻倍周期 2.9–6.5 个月 |
| 验证 | 人工标注（`annotate/`） | 8 档时长 + 3 种类型，分层抽样 300 项任务 |

**为什么自己估计时长。** 目前没有公开数据集给出全部 O\*NET 任务的端到端时长。最接近的是 Hatgis-Kessell et al. (2026)，但他们估计的单次时长 *w* 上限是 7 小时。这个上限用来算时间占比没问题，用来和 AI 的时间跨度比就太短了。他们的数据在这里只用来对照，不进入网站数据。

**为什么时间占比里每次最多按一个工作日算。** O\*NET 问的是从业者**多久做一次**这项工作（比如「每天」），不是多久**完成一次**。一个要几百小时的研究项目如果每天都在做，不设上限就会算成每天 300 小时。设上限避免了这个问题，代价是长任务的分量被低估（见「局限」）。

## 目前的结果

**时长估计。** 17,525 项任务在一张 A100 40GB 上用了 3.96 小时，输出 1,261 tokens/s；按 1.99 美元/小时算，约每 1,000 项任务 0.45 美元。

和 51 条人工标注（单人标注，8 档时长）的对比：

| prompt | 相差 ≤1 档 | 二次加权 kappa | Spearman | 长任务（≥4 小时）偏差 | 类型一致 |
|---|---|---|---|---|---|
| v2 | 75% | 0.58 | 0.69 | +0.22 档 | 84% |
| v3 | 94% | 0.70 | 0.64 | −0.50 档 | 86% |
| **v3.1（采用）** | 86% | 0.70 | 0.72 | 0.00 档 | 86% |

这 51 条用来调过 prompt，属于开发集。

**独立测试集（第 54–103 条，没参与调参）。** 由 AI 标注者（Claude Opus 5.5）按同一份人工标注规则标注，标注时不看模型的估计。v3.1 有 82% 与它相差不超过一档（二次加权 κ 0.67），类型一致 84%，平均偏长 0.56 档，主要在短任务上。这是和另一个模型的一致率，不是人工验证的准确率。

- v2 把短任务估长了；v3 修好了短任务，却把长任务砍掉一半，会让倒计时显得更早；v3.1 把「不要夸大」的规则限制在例行小动作上。
- Hatgis-Kessell et al. 的 *w* 和同一批人工标注相差 ≤1 档的只有 51%，平均偏短 1.45 档。顶在 7 小时上限的 214 项任务，我们估计的中位数是 38 小时，86% 超过 7 小时。
- 把时间占比换成 Hatgis-Kessell et al. 的版本，85% 的职业倒计时变化不到半年（各职业倒计时的排序相关 0.87）。

## 网站

静态网站：一个 HTML 文件加两个数据文件（`web/occupations.json` 约 2 MB，`web/news.json`），没有后端，所有计算都在浏览器里完成。

- **搜索**：支持中英文；876 个职业都有中文名，约 120 个常见职业另有别名（比如「程序员」「码农」）。
- **七段数码管倒计时**：倒数到「实际落地」；同时显示「能力到位」和「实际落地」两个日期，以及按 METR 不同翻倍周期算出的区间。
- **假设控制**：可靠度（50% 或 80%）、翻倍周期、真实工作难度折扣、落地期、人际信任类任务的额外落地期，以及倒计时对应的比例（一半或四分之三工作时间）。
- **任务时间线**：每项任务的能力到位时间和落地期；需要现场操作的任务标为「趋势线不覆盖」。
- **领域动态**：按职业所属领域（22 个 SOC 大类）显示 AI 新闻，每条标明是「AI 进展」还是「现实检验」。少数职业有人工挑选的新闻置顶，其余由 `news/collect.py` 每天自动抓取（见下文）。下面还有一个搜索框，按职业实时搜 Google News 的最新报道（默认关键词是「职业名 AI」，可以改；跑两组查询，按标题粗分成「AI 进展」和「现实检验」），通过 Cloudflare Pages Function `functions/api/search.js` 在服务器端查询，不需要 API key，结果缓存 6 小时。
- **分享**：浏览器里画分享图（竖版 4:5 或方形 1:1，中英文），二维码打开同一个职业和同一组假设；另有 LinkedIn、X、手机系统分享、复制链接和复制文案。链接里带着假设（`?lang=zh&d=2.9&k=8#15-1252.00`），别人打开看到的是同一组数字。
- **中英双语**：语言按 `?lang=zh|en`、上次的选择、浏览器语言的顺序决定。

## 仓库结构

| 目录 | 内容 |
|---|---|
| `annotate/` | Streamlit 标注工具、标注规则、一致性计算 |
| `estimate/` | vLLM 批量推理、prompt、与人工标注的对比评估 |
| `forecast/` | METR 趋势拟合、回测、倒计时算法 |
| `web/` | 网站、生成网站数据的脚本、时间占比公式、`news.json`、二维码库（`vendor/`） |
| `news/` | 领域划分和搜索词、人工挑选的新闻、每日新闻抓取脚本 |
| `functions/` | 实时新闻搜索接口（Cloudflare Pages Function，`/api/search`） |
| `tests/` | pytest 测试 |
| `docs/` | 设计文档（中英文） |
| `data/`、`runs/` | 第三方数据和模型输出，不提交到仓库 |

## 运行

```bash
# 1. 数据（data/ 和 runs/ 不在仓库里，需要自己建）：
#    data/Task Ratings.xlsx               ← O*NET 30.2：https://www.onetcenter.org/dl_files/database/db_30_2_excel.zip
#    data/task_time_share_estimates.xlsx  ← https://github.com/Stephanehk/Estimating-Time-Spent-On-Work
#                                            （第 2 步的任务清单，以及可选的对照）

# 2. 估计任务时长（需要 GPU，一张 A100 40GB 约 4 小时）
cd estimate
bash setup.sh
python prepare_tasks.py --xlsx ../data/task_time_share_estimates.xlsx --out tasks.jsonl
python estimate.py --tasks tasks.jsonl --out ../runs/full-v3.1 --max-tokens 600

# 3. 生成网站数据并本地预览
cd ../web
python build_data.py                     # 用我们的时间占比（默认）
python build_data.py --shares stanford   # 对照：用 Hatgis-Kessell et al. 的时间占比
python -m http.server 8000               # 打开 http://localhost:8000（没有实时新闻搜索）
# 或者在仓库根目录运行，带上新闻搜索接口：npx wrangler pages dev web

# 4. 新闻（可选；GitHub Action 每天自动跑）
cd ..
python news/collect.py -v                # 按领域抓 Google News RSS → web/news.json
# 设了 NEWS_LLM_API_KEY（任何 OpenAI 兼容接口，另有 NEWS_LLM_BASE_URL / NEWS_LLM_MODEL）就用 LLM 筛选、分类并翻译成中文；
# 不设就用关键词规则，只保留英文标题
```

**标注。** 见 [`annotate/README.md`](annotate/README.md) 和 [`annotate/GUIDELINES.md`](annotate/GUIDELINES.md)。每位标注者在自己电脑上运行 `streamlit run label_app.py`，标完把 `labels_<名字>.csv` 直接发给对方。标注结果不提交到仓库，保证标注者之间互相独立。

## 测试与 CI/CD

```bash
pip install -r requirements-dev.txt
pytest -q
```

测试覆盖 prompt 解析、用 mock 后端端到端跑通估计流程（包括断点续跑）、倒计时算法、时间占比公式、新闻抓取（RSS 解析、筛选、合并，不联网）和网站数据格式。

- `.github/workflows/ci.yml`：每次 push 和 PR 自动运行 lint 和测试。
- `.github/workflows/deploy.yml`：把 `web/` 部署到 Cloudflare Pages，目前只能手动触发。
- `.github/workflows/news.yml`：每天抓一次新闻，`web/news.json` 有变化就提交。仓库 Secret 里设 `NEWS_LLM_API_KEY` 才有中文标题；上线后把变量 `NEWS_AUTO_DEPLOY` 设为 `true`，新闻更新时会自动重新部署。

## 局限

- **时间占比低估长任务**：每次执行最多按一个工作日算。软件、研究这类长任务多的职业，倒计时可能偏早约一年。
- **METR 的任务以软件工程为主**：真实工作难度折扣还没校准，这是下一阶段的核心研究问题。
- **短任务（1 小时以内）被估长**约 1 档。它们本来就在 AI 当前能力范围内，对倒计时影响很小。
- **任务类型不完美**：管理、评估下属这类任务容易分错；当面护理类任务常被标成「人际信任」。
- **验证**：开发集是一位人工标注者，独立测试集是一个 AI 标注者，还没有标注者间一致性。

## 数据来源

- O\*NET 30.2 Database，美国劳工部就业与培训管理局（CC BY 4.0）
- METR，*Time Horizon 1.1*
- 仅作对照：Hatgis-Kessell, Aguirre, Wan & Bommasani (2026), *Estimating Time Spent on Work Tasks*, arXiv:2608.05172
