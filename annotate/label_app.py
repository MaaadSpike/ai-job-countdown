"""M3 评测集标注页。

用法：
    streamlit run label_app.py

两个人各自在自己电脑上跑，各自输入名字，结果分别存成 labels_<名字>.csv。
关掉再打开会从上次停下的地方继续。标完之后用 agreement.py 计算两人一致性。
"""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

SAMPLE_PATH = Path("eval_sample.csv")

BINS = [
    (1, "15 分钟以内"),
    (2, "15 分钟 – 1 小时"),
    (3, "1 – 4 小时"),
    (4, "4 – 8 小时（约一天）"),
    (5, "1 – 5 天（8–40 小时）"),
    (6, "1 – 4 周（40–160 小时）"),
    (7, "1 – 3 个月（160–500 小时）"),
    (8, "3 个月以上"),
]
BIN_LABEL = {b: f"{b} · {t}" for b, t in BINS}

TYPES = [
    ("digital", "数字：核心产出是文字、数字、代码、图片或文件"),
    ("physical", "物理操作：需要亲手操作实物，或必须到现场"),
    ("trust", "人际信任：价值主要来自当面沟通、说服或建立信任"),
]
TYPE_LABEL = dict(TYPES)
TYPE_KEYS = [k for k, _ in TYPES]

GUIDE = """
**时长：端到端完成一次要多少专注工作时间**

- 从开始做到交付成果，一共要花多少**实际动手的时间**。可以跨好几天，把每次投入的时间加起来。
  例：「写一份尽职调查报告」= 从开始收集材料到交出完整报告，累计投入的小时数。
- **不算等待**：等审批、等回复、等材料到位的时间都不算。
- 估「做一次」，不是一年里花在这上面的总时间。例：「准备纳税申报」= 做完一份申报。
- 假设做的人是**熟练从业者**：做这行几年，并且**已经熟悉手头的材料和系统**，不需要先花时间了解背景。
- 假设**不用 AI 工具**。
- 拿不准在两档之间时，选更可能的那档，并在备注里写一句。

**类型：这条任务的核心靠什么完成**（选最主要的一项）

- **数字**：核心产出是文字、数字、代码、图片或文件，原则上在电脑上就能完成。
  例：写护理记录、起草合同、做报表、设计海报。
- **物理操作**：必须亲手操作实物或到现场。
  例：给病人静脉给药、修水管、现场勘查、开车送货。
- **人际信任**：可以远程或在电脑上完成，但价值主要来自当面沟通、说服或建立信任。
  例：向客户解释税务方案、安抚情绪激动的客户、谈判合同条款、面试候选人。

**完全不懂这个职业**：点「跳过」，不要硬猜。
"""


@st.cache_data
def load_sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE_PATH, dtype={"task_id": str, "onet_code": str, "major_group": str}).fillna("")


def labels_path(name: str) -> Path:
    safe = "".join(c for c in name if c.isalnum() or c in "-_") or "anon"
    return Path(f"labels_{safe}.csv")


def load_labels(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, dtype={"task_id": str})
    return pd.DataFrame(columns=["task_id", "annotator", "duration_bin", "task_type",
                                 "skipped", "note", "labeled_at"])


def save_label(path: Path, row: dict) -> None:
    df = load_labels(path)
    df = df[df["task_id"] != row["task_id"]]
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


st.set_page_config(page_title="M3 标注", layout="wide")

if not SAMPLE_PATH.exists():
    st.error("找不到 eval_sample.csv。先运行 `python sample_tasks.py` 生成待标注清单，再打开这个页面。")
    st.stop()

sample = load_sample()

with st.sidebar:
    st.header("标注说明")
    st.markdown(GUIDE)

name = st.text_input("你的名字（两人用不同的名字，结果分开保存）", key="annotator")
if not name.strip():
    st.info("先输入名字再开始。")
    st.stop()

path = labels_path(name.strip())
labels = load_labels(path)
done_ids = set(labels["task_id"])

calib_only = st.toggle("只看试标集（前 20 条：先各自标，再一起对答案）", value=True)
items = sample[sample["calibration"] == 1] if calib_only else sample
todo = items[~items["task_id"].isin(done_ids)]

n_done = int(items["task_id"].isin(done_ids).sum())
st.progress(n_done / len(items), text=f"已标 {n_done} / {len(items)} 条 · 结果保存在 {path}")

if "jump" in st.session_state and st.session_state.jump in set(items["task_id"]):
    current = items[items["task_id"] == st.session_state.jump].iloc[0]
elif len(todo):
    current = todo.iloc[0]
else:
    st.success("这一组已经全部标完。" + ("关掉上面的开关继续标剩下的条目。" if calib_only else "可以运行 agreement.py 计算一致性了。"))
    current = None

if current is not None:
    prev = labels[labels["task_id"] == current["task_id"]]
    prev = prev.iloc[0] if len(prev) else None

    st.caption(f"第 {current['item_no']} 条 · {current['major_group_name']} · O*NET {current['onet_code']}"
               + (" · 试标" if int(current["calibration"]) == 1 else ""))
    st.subheader(current["occupation"])
    if current["occupation_description"]:
        with st.expander("这个职业是做什么的"):
            st.write(current["occupation_description"])
    st.markdown(f"### {current['task']}")

    with st.form(f"form_{current['task_id']}", clear_on_submit=False):
        default_bin = None
        if prev is not None and pd.notna(prev["duration_bin"]):
            default_bin = int(prev["duration_bin"]) - 1
        duration = st.radio("熟练从业者端到端完成一次，累计要多少专注工作时间", [b for b, _ in BINS],
                            index=default_bin, format_func=lambda b: BIN_LABEL[b], horizontal=True)
        default_type = None
        if prev is not None and isinstance(prev["task_type"], str) and prev["task_type"] in TYPE_KEYS:
            default_type = TYPE_KEYS.index(prev["task_type"])
        task_type = st.radio("这条任务的核心靠什么完成", TYPE_KEYS, index=default_type,
                             format_func=lambda k: TYPE_LABEL[k])
        note = st.text_input("备注（可选）", value="" if prev is None or pd.isna(prev["note"]) else str(prev["note"]))
        c1, c2 = st.columns([1, 1])
        submit = c1.form_submit_button("保存并下一条", type="primary", use_container_width=True)
        skip = c2.form_submit_button("跳过（不懂这个职业）", use_container_width=True)

    if submit or skip:
        if submit and (duration is None or task_type is None):
            st.error("两个问题都要选一个答案；完全不懂的话点「跳过」。")
        else:
            save_label(path, {
                "task_id": current["task_id"],
                "annotator": name.strip(),
                "duration_bin": None if skip else int(duration),
                "task_type": None if skip else task_type,
                "skipped": int(bool(skip)),
                "note": note,
                "labeled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            st.session_state.pop("jump", None)
            st.rerun()

st.divider()
with st.expander("修改已标的条目"):
    if len(labels):
        merged = labels.merge(sample[["task_id", "item_no", "occupation", "task"]], on="task_id").sort_values("item_no")
        pick = st.selectbox("选一条重新标", merged["task_id"],
                            format_func=lambda t: f"#{int(merged.loc[merged.task_id == t, 'item_no'].iloc[0])} "
                                                  f"{merged.loc[merged.task_id == t, 'task'].iloc[0][:60]}")
        if st.button("打开这一条"):
            st.session_state.jump = pick
            st.rerun()
    else:
        st.write("还没有已标的条目。")
