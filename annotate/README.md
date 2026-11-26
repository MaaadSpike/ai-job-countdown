# 人工标注（M3）

给 300 条 O*NET 任务标「做一次要多久」和「属于哪类任务」，用来检验模型估计的准确度。

## 开始

```bash
git clone <repo 地址>
cd ai-job-countdown/annotate
pip install -r requirements.txt
streamlit run label_app.py
```

浏览器会自动打开标注页。先读 [GUIDELINES.md](GUIDELINES.md)。

1. 输入**你自己的名字**（两个人名字不同，结果分开保存）。
2. **试标**：打开「只看试标集」，标前 20 条。各自标，标完再一起对答案、统一规则。
3. **正式标**：关掉开关，标到第 100 条。两个人标的是同样的 100 条。
4. 结果在 `labels_<你的名字>.csv`，关掉再打开会接着上次的进度。标完把这个文件**直接发给对方**，不要提交到仓库。

页面右上角的 Deploy 不用管，在自己电脑上跑就行。

## 一致性（两人都标完后）

```bash
python agreement.py labels_A.csv labels_B.csv
```

- 打印时长的二次加权 kappa、Spearman 相关，以及类型的 kappa
- `disagreements.csv`：时长差 2 档以上，或类型不同的条目，两人一起讨论
- `eval_labels.csv`：最终评测集

## AI 标注者（可选）

`ai_label.py` 让一个大模型按 [GUIDELINES.md](GUIDELINES.md) 的同一套规则标注，输出和标注页一样的 `labels_<名字>.csv`。
它只用人工标注规则，不用 M2 的 prompt，也不看 M2 的估计。尽量选和 M2（Qwen）不同家族的模型。

```bash
pip install -r requirements.txt
export AI_LABEL_API_KEY=...        # 对应接口的 key

# 1) 先在已有人工标注的条目上检验 AI 标注者本身
python ai_label.py --items 1-51 --name ai-deepseek --base-url https://api.deepseek.com/v1 --model deepseek-chat
python agreement.py labels_spike.csv labels_ai-deepseek.csv

# 2) 再标独立测试集（换一个名字，和上面分开存），用 M2 结果对比
python ai_label.py --items 52-100 --name ai-deepseek-test --base-url https://api.deepseek.com/v1 --model deepseek-chat
python ../estimate/evaluate.py --estimates ../runs/full-v3.1/estimates.jsonl --labels labels_ai-deepseek-test.csv
```

- 用 Gemini：`--base-url https://generativelanguage.googleapis.com/v1beta/openai/ --model gemini-3.8-flash --reasoning-effort low`，key 在 Google AI Studio 申请
- `--samples 3`：每条问 3 次，时长取中位数档、类型取多数票，更稳但贵 3 倍
- 接口不支持 `response_format`（比如部分 Anthropic 兼容端点）时加 `--no-json-mode`
- 中断后重跑同一条命令会跳过已经标过的条目
- 对外报告写「与 AI 标注者（模型名）的一致率」，不要写成人工校验或准确率
