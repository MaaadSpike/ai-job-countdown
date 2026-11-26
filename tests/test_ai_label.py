"""annotate/ai_label.py：解析、多次采样合并、断点续跑，以及输出能直接给 agreement.py 和 evaluate.py 用。"""
import json
import subprocess
import sys
from pathlib import Path

import ai_label
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def test_parse_valid_skip_and_bad():
    ok = ai_label.parse('Sure: {"instance": "One return", "duration_bin": "3", "task_type": "Digital", "note": "assume simple"}')
    assert ok == {"skip": False, "duration_bin": 3, "task_type": "digital", "note": "One return | assume simple"}
    assert ai_label.parse('{"skip": true, "note": "unclear task"}') == {"skip": True, "note": "unclear task"}
    assert ai_label.parse('{"duration_bin": 9, "task_type": "digital"}') is None
    assert ai_label.parse('{"duration_bin": 2, "task_type": "remote"}') is None
    assert ai_label.parse("no json") is None


def test_combine_median_bin_and_majority_type():
    ps = [{"skip": False, "duration_bin": b, "task_type": t, "note": "x"}
          for b, t in [(2, "digital"), (4, "physical"), (3, "digital")]]
    c = ai_label.combine(ps + [None])
    assert c["duration_bin"] == 3 and c["task_type"] == "digital" and c["note"].startswith("[3 次采样")
    assert ai_label.combine([None, {"skip": True, "note": "?"}]) == {"skip": True, "note": "?"}
    assert ai_label.combine([None]) is None


def test_prompt_uses_guideline_rules_not_m2():
    msgs = ai_label.build_messages({"occupation": "Accountants", "onet_code": "13-2011.00", "task": "Audit books.",
                                    "occupation_description": "Examine financial records."})
    sys_txt = msgs[0]["content"]
    assert "8. more than 3 months" in sys_txt and "stop at the first that applies" in sys_txt
    assert "Calibration examples" not in sys_txt  # 不带 M2 的校准例子
    assert "Occupation description: Examine financial records." in msgs[1]["content"]


def test_mock_run_resume_and_agreement(tmp_path):
    sample = pd.read_csv(ROOT / "annotate" / "eval_sample.csv", dtype={"task_id": str})
    (tmp_path / "eval_sample.csv").write_text(sample.to_csv(index=False), encoding="utf-8")
    cmd = [sys.executable, str(ROOT / "annotate" / "ai_label.py"), "--backend", "mock", "--name", "ai-mock", "--items", "1-10"]
    r1 = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    out = pd.read_csv(tmp_path / "labels_ai-mock.csv", dtype={"task_id": str})
    assert list(out.columns) == ai_label.COLUMNS and len(out) == 10
    r2 = subprocess.run(cmd[:-1] + ["1-12"], cwd=tmp_path, capture_output=True, text=True)
    assert "本次 2 条" in r2.stdout
    assert len(pd.read_csv(tmp_path / "labels_ai-mock.csv")) == 12

    # 造一份「人工」标注，确认 agreement.py 能直接读 AI 的输出
    human = out.assign(annotator="human", duration_bin=4, task_type="digital")
    human.to_csv(tmp_path / "labels_human.csv", index=False)
    r3 = subprocess.run([sys.executable, str(ROOT / "annotate" / "agreement.py"), "labels_human.csv", "labels_ai-mock.csv"],
                        cwd=tmp_path, capture_output=True, text=True)
    assert r3.returncode == 0, r3.stderr
    assert "共同标注 10 条" in r3.stdout

    # evaluate.py 直接读单个标注者的 labels 文件
    est = tmp_path / "estimates.jsonl"
    est.write_text("\n".join(json.dumps({"task_id": t, "onet_code": "x", "occupation": "o", "task": "t", "hours": 2.0,
                                         "task_type": "digital", "n_valid": 5}) for t in out["task_id"]), encoding="utf-8")
    r4 = subprocess.run([sys.executable, str(ROOT / "estimate" / "evaluate.py"), "--estimates", str(est),
                         "--labels", str(tmp_path / "labels_ai-mock.csv")], capture_output=True, text=True)
    assert r4.returncode == 0, r4.stderr
    assert "标注来自单个标注者：ai-mock" in r4.stdout and "可比较的任务：" in r4.stdout


def test_bad_key_and_fatal_errors_stop_early(tmp_path, monkeypatch):
    sample = pd.read_csv(ROOT / "annotate" / "eval_sample.csv", dtype={"task_id": str})
    (tmp_path / "eval_sample.csv").write_text(sample.to_csv(index=False), encoding="utf-8")
    env = {**__import__("os").environ, "AI_LABEL_API_KEY": "你的DeepSeek key"}
    r = subprocess.run([sys.executable, str(ROOT / "annotate" / "ai_label.py"), "--name", "x", "--items", "1-3"],
                       cwd=tmp_path, capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "API key 看起来不对" in r.stderr
    assert not (tmp_path / "labels_x.csv").exists()

    class AuthenticationError(Exception):
        pass

    def bad(_):
        raise AuthenticationError("401 invalid key")
    try:
        ai_label.label_one(bad, {"item_no": 1, "occupation": "o", "onet_code": "x", "task": "t"}, 1)
        raise AssertionError("should stop")
    except ai_label.FatalError as e:
        assert "401" in str(e)
