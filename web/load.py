"""读入 M2 结果和斯坦福时间占比，合成一张 DataFrame（build_data.py 用）。
默认路径相对仓库根目录，可以用环境变量 M2_ESTIMATES、TIME_SHARES 覆盖。"""
import json
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EST = os.environ.get("M2_ESTIMATES", os.path.join(ROOT, "runs/full-v3.1/estimates.jsonl"))
XLSX = os.environ.get("TIME_SHARES", os.path.join(ROOT, "data/task_time_share_estimates.xlsx"))


def load_frame(est_path: str = EST, xlsx_path: str | None = XLSX) -> pd.DataFrame:
    """xlsx_path=None 时不读斯坦福的文件（--shares own 模式），per_day 和 share 留空。"""
    m2 = pd.DataFrame([json.loads(line) for line in open(est_path, encoding="utf-8")])
    m2["task_id"] = m2["task_id"].astype(str)
    if xlsx_path is None:
        return m2.assign(w=float("nan"), freq=float("nan"), per_day=float("nan"), share=float("nan"))
    st = pd.read_excel(xlsx_path)
    st.columns = ["task_id", "task_name", "onet_code", "occ", "per_day", "w", "freq"]
    st["task_id"] = st["task_id"].astype(str)
    df = m2.merge(st[["task_id", "onet_code", "w", "freq", "per_day"]], on=["task_id", "onet_code"], how="left")
    df["share"] = df["per_day"] / df.groupby("onet_code")["per_day"].transform("sum")
    return df
