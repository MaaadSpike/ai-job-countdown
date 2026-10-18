import json

from prompt import SCHEMA, TASK_TYPES, build_messages, parse


def test_parse_valid_output():
    text = json.dumps({"instance": "one return", "steps": [{"step": "fill", "hours": 1.5}],
                       "hours_low": 1, "hours_typical": 1.5, "hours_high": 3, "task_type": "digital"})
    p = parse(text)
    assert p["hours_typical"] == 1.5 and p["task_type"] == "digital" and p["step_sum"] == 1.5


def test_parse_repairs_inconsistent_bounds():
    p = parse(json.dumps({"hours_low": 5, "hours_typical": 2, "hours_high": 1, "task_type": "trust"}))
    assert p["hours_low"] <= p["hours_typical"] <= p["hours_high"]


def test_parse_rejects_bad_outputs():
    assert parse("not json") is None
    assert parse(json.dumps({"hours_low": 1, "hours_typical": 0, "hours_high": 2, "task_type": "digital"})) is None
    assert parse(json.dumps({"hours_low": 1, "hours_typical": 1, "hours_high": 2, "task_type": "robot"})) is None


def test_schema_allows_single_step():
    assert SCHEMA["properties"]["steps"]["minItems"] == 1
    assert SCHEMA["properties"]["task_type"]["enum"] == TASK_TYPES


def test_build_messages_includes_task():
    msgs = build_messages({"occupation": "Barbers", "onet_code": "39-5011.00", "task": "Cut hair."})
    assert msgs[0]["role"] == "system" and "Cut hair." in msgs[1]["content"]
