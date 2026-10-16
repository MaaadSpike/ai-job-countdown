"""最简版倒计时算法：输入一个职业的任务列表和几个全局参数，输出 AI 能力到位时间和倒计时终点。"""
import math
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class Task:
    name: str
    hours: float | None   # 熟练从业者做一次要几小时；None = 需要现场操作或人际信任
    share: float          # 占工作时间的比例，0–1
    messiness: float = 1.0  # 复杂度折扣，>=1；2 表示比 METR 的题难一倍


def months_until_capable(task: Task, h0: float, doubling_months: float) -> float:
    """单条任务：AI 能力上限越过这条任务还要几个月。0 = 现在就能，inf = METR 趋势线不覆盖（不代表永远不会）。"""
    if task.hours is None:
        return math.inf
    effective = task.hours * task.messiness
    return max(0.0, doubling_months * math.log2(effective / h0))


def forecast(tasks: list[Task], h0: float = 3.1, doubling_months: float = 7.0,
             threshold: float = 0.5, adoption_years: float = 2.0, today: date | None = None):
    today = today or date.today()
    timed = sorted(((months_until_capable(t, h0, doubling_months), t) for t in tasks), key=lambda x: x[0])

    cum = 0.0
    capable_months = None
    for months, t in timed:
        if math.isinf(months):
            break
        cum += t.share
        if cum >= threshold - 1e-9:
            capable_months = months
            break

    covered = sum(t.share for t in tasks if t.hours is not None)
    if capable_months is None:
        return {"reachable": False, "covered_share": covered, "per_task": timed}

    capable_date = today + timedelta(days=capable_months * 30.4375)
    end_date = capable_date + timedelta(days=adoption_years * 365.25)
    return {"reachable": True, "capable_months": capable_months, "capable_date": capable_date,
            "end_date": end_date, "per_task": timed}


if __name__ == "__main__":
    accountant = [
        Task("录入和核对凭证", 0.5, 0.20),
        Task("银行对账", 2, 0.15),
        Task("编制月末结账", 16, 0.20),
        Task("准备报税申报", 10, 0.15),
        Task("审计底稿", 30, 0.10),
        Task("判断特殊交易的会计处理", 12, 0.10),
        Task("向客户解释税务方案", None, 0.10),
    ]
    for m in (1.0, 2.0):
        for t in accountant:
            t.messiness = m
        r = forecast(accountant, today=date(2026, 10, 14))
        print(f"复杂度折扣 m={m}: 能力到位 {r['capable_months']:.1f} 个月后（{r['capable_date']}），"
              f"倒计时终点 {r['end_date']}")
    print("\n各任务（m=1）：")
    for t in accountant:
        t.messiness = 1.0
    for months, t in forecast(accountant, today=date(2026, 10, 14))["per_task"]:
        print(f"  {t.name:<14} {'趋势线不覆盖' if math.isinf(months) else f'{months:5.1f} 个月'}")
