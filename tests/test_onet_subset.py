"""check_onet_subset：任务清单能否只靠 O*NET 重建。用 O*NET Task Ratings 格式的小样例，不需要真实数据。"""
import pandas as pd
from check_onet_subset import compare, onet_rated_tasks


def _ratings():
    rows = []
    for code, title, tid, task, scales in [
        ("15-1252.00", "Software Developers", 101, "Write code.", ["FT", "RT", "IM"]),
        ("15-1252.00", "Software Developers", 102, "Test  software.", ["FT", "RT"]),
        ("15-1252.00", "Software Developers", 103, "Only importance rated.", ["IM"]),
        ("13-2011.00", "Accountants and Auditors", 201, "Audit books.", ["FT", "RT"]),
    ]:
        for s in scales:
            rows.append({"O*NET-SOC Code": code, "Title": title, "Task ID": tid, "Task": task, "Scale ID": s,
                         "Category": 5 if s == "FT" else None, "Data Value": 50.0})
    return pd.DataFrame(rows)


def test_rated_tasks_need_ft_and_rt():
    t = onet_rated_tasks(_ratings())
    assert sorted(t.task_id) == ["101", "102", "201"]


def test_compare_reports_coverage_and_text():
    est = pd.DataFrame([
        {"onet_code": "15-1252.00", "task_id": "101", "task": "Write code."},
        {"onet_code": "15-1252.00", "task_id": "102", "task": "Test software."},  # 空格不同，算一致
        {"onet_code": "15-1252.00", "task_id": "999", "task": "Not in O*NET."},
    ])
    r = compare(est, onet_rated_tasks(_ratings()))
    assert r["estimated"] == 3 and r["in_onet"] == 2 and r["same_text"] == 2
    assert r["missing_from_onet"] == [("15-1252.00", "999")]
    assert r["onet_not_estimated"] == 1 and r["onet_occ_not_estimated"] == 1
