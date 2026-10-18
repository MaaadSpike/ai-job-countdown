import math
from datetime import date

from task_forecast import Task, forecast, months_until_capable


def test_months_until_capable():
    assert months_until_capable(Task("short", 1.0, 0.5), h0=3.1, doubling_months=7) == 0
    assert math.isclose(months_until_capable(Task("x", 12.4, 0.5), h0=3.1, doubling_months=6), 12.0)
    assert math.isinf(months_until_capable(Task("onsite", None, 0.5), h0=3.1, doubling_months=6))
    assert math.isclose(months_until_capable(Task("messy", 3.1, 0.5, messiness=4), 3.1, 6), 12.0)


def test_forecast_threshold_and_coverage():
    tasks = [Task("a", 1, 0.3), Task("b", 12.4, 0.3), Task("c", None, 0.4)]
    r = forecast(tasks, h0=3.1, doubling_months=6, threshold=0.5, today=date(2026, 1, 1))
    assert r["reachable"]
    r2 = forecast(tasks, h0=3.1, doubling_months=6, threshold=0.75, today=date(2026, 1, 1))
    assert not r2["reachable"] and math.isclose(r2["covered_share"], 0.6)
