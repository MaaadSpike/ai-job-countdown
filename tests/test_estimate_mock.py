"""用 mock 后端跑通 estimate.py 的完整流程：写 raw、断点续跑、汇总。"""
import json
import subprocess
import sys
from pathlib import Path

ESTIMATE = Path(__file__).resolve().parents[1] / "estimate" / "estimate.py"
TASKS = [{"task_id": str(i), "onet_code": "11-1011.00", "occupation": "Chief Executives", "task": f"Task {i}."}
         for i in range(5)]


def run(tmp_path, *extra):
    return subprocess.run([sys.executable, str(ESTIMATE), "--backend", "mock", "--tasks", str(tmp_path / "t.jsonl"),
                           "--out", str(tmp_path / "out"), "--batch-size", "2", *extra],
                          capture_output=True, text=True, check=True, cwd=ESTIMATE.parent)


def test_mock_run_and_resume(tmp_path):
    (tmp_path / "t.jsonl").write_text("\n".join(json.dumps(t) for t in TASKS))
    run(tmp_path, "--limit", "3")
    run(tmp_path)  # 续跑：只补剩下的 2 条
    raw = (tmp_path / "out" / "raw.jsonl").read_text().splitlines()
    est = [json.loads(l) for l in (tmp_path / "out" / "estimates.jsonl").read_text().splitlines()]
    assert len(raw) == 5 and len(est) == 5
    assert all(e["n_valid"] == 5 and e["hours"] > 0 and e["task_type"] in {"digital", "physical", "trust"} for e in est)
    stats = json.loads((tmp_path / "out" / "run_stats.json").read_text())
    assert [s["n_tasks"] for s in stats] == [3, 2]
