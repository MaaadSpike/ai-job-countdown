import pandas as pd

from own_shares import FREQ_PER_DAY, WORKDAY, expected_freq, own_shares


def ratings():
    rows = []
    for task, cat in [(1, 5), (2, 4)]:  # 任务 1 每天做，任务 2 一周多次
        rows.append({"O*NET-SOC Code": "15-1252.00", "Task ID": task, "Scale ID": "FT", "Category": cat, "Data Value": 100.0})
        rows.append({"O*NET-SOC Code": "15-1252.00", "Task ID": task, "Scale ID": "RT", "Category": None, "Data Value": 100.0})
    return pd.DataFrame(rows)


def test_expected_freq():
    ef = expected_freq(ratings()).set_index("task_id")
    assert ef.loc["1", "freq_per_day"] == FREQ_PER_DAY[5] and ef.loc["2", "freq_per_day"] == FREQ_PER_DAY[4]


def test_shares_sum_to_one_and_cap_long_tasks():
    est = pd.DataFrame({"onet_code": ["15-1252.00"] * 2, "task_id": ["1", "2"], "hours": [2.0, 300.0]})
    d = own_shares(est, expected_freq(ratings())).set_index("task_id")
    assert abs(d.own_share.sum() - 1) < 1e-9
    expected_ratio = (FREQ_PER_DAY[4] * WORKDAY) / (FREQ_PER_DAY[5] * 2.0)
    assert abs(d.loc["2", "own_share"] / d.loc["1", "own_share"] - expected_ratio) < 1e-9
