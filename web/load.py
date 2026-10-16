"""读入 M2 结果和斯坦福时间占比，合成一张 DataFrame（build_data.py 用）。
路径相对仓库根目录：runs/full-v2/estimates.jsonl、data/task_time_share_estimates.xlsx。"""
import json, os, pandas as pd, numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EST = os.environ.get("M2_ESTIMATES", os.path.join(ROOT, "runs/full-v2/estimates.jsonl"))
XLSX = os.environ.get("TIME_SHARES", os.path.join(ROOT, "data/task_time_share_estimates.xlsx"))
m2 = pd.DataFrame([json.loads(l) for l in open(EST, encoding="utf-8")])
st = pd.read_excel(XLSX)
st.columns = ['task_id', 'task_name', 'onet_code', 'occ', 'per_day', 'w', 'freq']
m2['task_id'] = m2['task_id'].astype(str); st['task_id'] = st['task_id'].astype(str)
df = m2.merge(st[['task_id', 'onet_code', 'w', 'freq', 'per_day']], on=['task_id', 'onet_code'], how='left')
df['share'] = df['per_day'] / df.groupby('onet_code')['per_day'].transform('sum')
