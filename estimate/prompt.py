"""M2 的 prompt、输出 schema 和解析。改 prompt 时一定要改 PROMPT_VERSION，结果文件里会记录版本。"""
import json
import re

PROMPT_VERSION = "v2-2026-10-14"

TASK_TYPES = ["digital", "physical", "trust"]

SCHEMA = {
    "type": "object",
    "properties": {
        "instance": {"type": "string", "maxLength": 300},
        "steps": {
            "type": "array", "minItems": 2, "maxItems": 6,
            "items": {"type": "object",
                      "properties": {"step": {"type": "string", "maxLength": 120},
                                     "hours": {"type": "number", "minimum": 0}},
                      "required": ["step", "hours"], "additionalProperties": False},
        },
        "hours_low": {"type": "number", "minimum": 0},
        "hours_typical": {"type": "number", "minimum": 0},
        "hours_high": {"type": "number", "minimum": 0},
        "task_type": {"type": "string", "enum": TASK_TYPES},
    },
    "required": ["instance", "steps", "hours_low", "hours_typical", "hours_high", "task_type"],
    "additionalProperties": False,
}

SYSTEM = """You estimate how long work tasks take. You are careful, concrete, and calibrated.

For the given occupation and O*NET task statement, estimate the END-TO-END time for ONE typical instance of the task:
- Count the total focused working hours a skilled worker spends from starting the task to delivering its result. If one instance spans several days, weeks or months, add up the hours actually worked across all sessions. Do not cap estimates at a day or a week: project-scale tasks often take hundreds of hours.
- Do NOT count waiting time (approvals, replies, materials arriving, machines running unattended).
- One instance means doing the task once, not the total time spent on it over a year. Example: "Prepare tax returns" = one return.
- The worker is skilled (several years in the occupation) and already familiar with the relevant materials and systems, so do not count time to learn context.
- Assume the worker does NOT use generative AI tools.
- If the statement bundles several activities, estimate a typical instance of the main activity.

Method: first state in one sentence what one instance consists of. Then break it into 2-6 concrete steps and estimate the hours for each. Set hours_typical to roughly the sum of the steps, and give hours_low (10th percentile) and hours_high (90th percentile) for the whole instance. Use precise numbers (e.g. 0.3, 2.5, 14, 230), not only round values.

Classify what the core of the task depends on (pick the dominant one):
- "physical": it requires hands-on work with physical objects, or the worker must be physically present on site to do it. This includes tasks done on site with a device (operating a cash register at a counter, monitoring equipment on a plant floor, calling emergency services while on patrol).
- "trust": it could be done remotely, but its value comes mainly from in-person communication, persuasion, or building trust with people (counseling, negotiating, giving difficult news, interviewing).
- "digital": the core output is text, numbers, code, images, or files, and it could be done entirely at a computer from anywhere.

Calibration examples (other occupations):
- Barber, "Cut and trim hair": ~0.5 h typical, physical.
- Cashier, "Receive payment for purchases at the register": ~0.05 h typical, physical.
- Accountant, "Reconcile a bank statement to the general ledger": ~1.5 h typical, digital.
- Financial advisor, "Explain a retirement plan to a client and answer questions": ~1.5 h typical, trust.
- Management consultant, "Write a client report on market entry options": ~60 h typical, digital.
- Software developer, "Design and build a new mid-sized feature": ~80 h typical, digital.
- University researcher, "Conduct a study and publish the findings in a journal": ~600 h typical, digital.

Answer with JSON only."""

USER = """Occupation: {occupation} (O*NET-SOC {onet_code})
Task: {task}"""


def build_messages(row: dict) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER.format(**row)},
    ]


_JSON_RE = re.compile(r"\{.*\}", re.S)


def parse(text: str) -> dict | None:
    """解析模型输出；结构不对或数字不合理就返回 None（这次采样作废）。"""
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        lo, mid, hi = float(d["hours_low"]), float(d["hours_typical"]), float(d["hours_high"])
        t = str(d["task_type"]).strip().lower()
        steps = d.get("steps") or []
        step_sum = sum(float(s.get("hours", 0)) for s in steps if isinstance(s, dict))
    except (ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return None
    if t not in TASK_TYPES or not (0 < mid < 20000):
        return None
    lo, hi = min(lo, mid), max(hi, mid)
    lo = lo if lo > 0 else mid / 3
    reasoning = str(d.get("instance", d.get("reasoning", "")))[:300]
    return {"hours_low": lo, "hours_typical": mid, "hours_high": hi, "task_type": t,
            "step_sum": step_sum, "reasoning": reasoning}
