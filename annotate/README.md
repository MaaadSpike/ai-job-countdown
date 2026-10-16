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
