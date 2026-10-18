# AI Job Countdown

输入一个职业，按 AI agent 能力的增长趋势，估算 AI 能独立完成这个职业一半工作时间的时间点。

做法：把职业拆成 O*NET 任务，估计每项任务人做一次要多久，再套上 [METR](https://metr.org) 测得的 AI 时间跨度（time horizon）增长曲线。

> 进行中的研究项目。数字是基于明确假设的推算，不是预测，也不代表某个职业会消失。

## 目录

| 目录 | 内容 |
|---|---|
| `annotate/` | 人工标注工具和规则（Streamlit），检验模型估计的准确度 |
| `estimate/` | 用 vLLM 批量估计 17,525 项任务的端到端时长和类型 |
| `forecast/` | METR 时间跨度的趋势拟合、回测，以及按任务累加的倒计时算法 |
| `web/` | 静态网站和生成网站数据的脚本 |
| `data/` | 第三方数据，不提交，按下文下载 |
| `runs/` | 模型输出，不提交 |

## 数据流

```
O*NET 任务 + 时间占比 (data/)
        │
        ▼
estimate/  ──► runs/<run>/estimates.jsonl ──► web/build_data.py ──► web/occupations.json ──► web/index.html
        ▲                                             ▲
annotate/ ──► eval_labels.csv ──► estimate/evaluate.py │
                                                      │
forecast/  ── METR 趋势参数 ───────────────────────────┘
```

## 运行

```bash
# 1. 数据（data/ 和 runs/ 不在仓库里，自己建）：
#    data/Task Ratings.xlsx               ← O*NET 30.2：https://www.onetcenter.org/dl_files/database/db_30_2_excel.zip（必需）
#    data/task_time_share_estimates.xlsx  ← https://github.com/Stephanehk/Estimating-Time-Spent-On-Work（可选，只用于对照）
#    runs/full-v3.1/estimates.jsonl       ← 第 2 步的输出

# 2. 估计任务时长（需要 GPU，A100 40GB 上约 3.3 小时、4 美元）
cd estimate
bash setup.sh
python prepare_tasks.py --xlsx ../data/task_time_share_estimates.xlsx --out tasks.jsonl
python estimate.py --tasks tasks.jsonl --out ../runs/full-v2 --max-tokens 600

# 3. 生成网站数据，本地预览
cd ../web
python build_data.py                   # 时间占比：O*NET 频率 × M2 时长，需要 data/Task Ratings.xlsx
# 或：python build_data.py --shares stanford  # 对照：用 Hatgis-Kessell et al. 的时间占比
python -m http.server 8000   # 打开 http://localhost:8000
```

## 当前结果（第一期）

**任务时长估计**（`estimate/`，Qwen2.5-32B-Instruct-AWQ，vLLM，每条任务采样 5 次取中位数）

- 17,525 项任务，A100 40GB 上 3.96 小时，输出 1,261 tokens/s
- 和 51 条人工标注（单人）比较，8 档时长：

| prompt | 相差 ≤1 档 | 二次加权 kappa | Spearman | 长任务（≥4 小时）偏差 | 类型一致 |
|---|---|---|---|---|---|
| v2 | 75% | 0.58 | 0.69 | +0.22 档 | 84% |
| v3 | 94% | 0.70 | 0.64 | −0.50 档 | 86% |
| **v3.1（采用）** | 86% | 0.70 | 0.72 | 0.00 档 | 86% |

  这 51 条用于调 prompt（开发集），最终准确度要在另外一批没参与调参的标注上报告。
- 对比现有数据：Hatgis-Kessell et al. (2026) 的单次时长 w 与同一批人工标注相差 ≤1 档的只有 51%，平均偏短 1.45 档；其中 214 条顶在 7 小时上限的任务，M2 估计的中位数是 38 小时，86% 超过 7 小时。
- 已知局限：1 小时以内的短任务平均偏长约 1 档。这些任务本来就在 AI 当前能力范围内，对倒计时几乎没有影响。

## 测试与部署

```bash
pip install -r requirements-dev.txt
pytest -q          # prompt 解析、mock 后端端到端、倒计时算法、时间占比、网站数据格式
```

- `.github/workflows/ci.yml`：每次 push 和 PR 自动跑 lint 和测试
- `.github/workflows/deploy.yml`：把 `web/` 部署到 Cloudflare Pages，目前只能手动触发，网站公开后改成 push 时自动部署

## 数据来源

- 任务清单：[O*NET 30.2](https://www.onetcenter.org)（CC BY 4.0）
- 任务时间占比：O*NET 30.2 任务评分里的执行频率和相关度，乘以 M2 估计的单次时长（`web/own_shares.py`）
- 对照数据：Hatgis-Kessell et al. (2026), *Estimating Time Spent on Work Tasks*（只用于比较，不进入网站数据）
- AI 时间跨度：METR Time Horizon 1.1
