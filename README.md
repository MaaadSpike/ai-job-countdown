# Peter need to do
我把标注工具放到 GitHub 上了，已经邀请你进仓库，先去邮箱接受邀请。

然后在终端里运行（需要先装好 Python）：

git clone https://github.com/MaaadSpike/ai-job-countdown.git
cd ai-job-countdown/annotate
pip install -r requirements.txt
streamlit run label_app.py

浏览器会自动打开标注页面。开始之前先读一下 annotate/GUIDELINES.md 里的标注规则，大概 3 分钟。

步骤：
1. 输入你的名字（英文，和我的不一样就行）
2. 保持「只看试标集」开关打开，先标前 20 条。自己独立判断，不要查资料，也不要问 AI
3. 标完 20 条告诉我，我们约个时间一起对答案、统一标准
4. 之后关掉开关，继续标到第 100 条

结果会存在 annotate 文件夹里的 labels_你的名字.csv，直接发给我就行，不要 push 到仓库。
页面右上角的 Deploy 不用管。

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
# 1. 数据：从 https://github.com/Stephanehk/Estimating-Time-Spent-On-Work 下载
#    task_time_share_estimates.xlsx，放到 data/

# 2. 估计任务时长（需要 GPU，A100 40GB 上约 3.3 小时、4 美元）
cd estimate
bash setup.sh
python prepare_tasks.py --xlsx ../data/task_time_share_estimates.xlsx --out tasks.jsonl
python estimate.py --tasks tasks.jsonl --out ../runs/full-v2 --max-tokens 600

# 3. 生成网站数据，本地预览
cd ../web
python build_data.py
python -m http.server 8000   # 打开 http://localhost:8000
```

## 数据来源

- 任务清单：[O*NET 30.2](https://www.onetcenter.org)（CC BY 4.0）
- 任务时间占比：Hatgis-Kessell et al. (2026), *Estimating Time Spent on Work Tasks*
- AI 时间跨度：METR Time Horizon 1.1
