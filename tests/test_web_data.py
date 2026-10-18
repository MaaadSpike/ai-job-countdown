"""web/occupations.json 的格式检查。文件不在仓库里时跳过（标注完成前不提交）。"""
import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "web" / "occupations.json"


@pytest.mark.skipif(not DATA.exists(), reason="occupations.json 还没生成")
def test_occupations_json_schema():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    assert d["meta"]["n_occ"] == len(d["occ"]) > 0
    codes = set()
    for code, en, zh, aliases, tasks in d["occ"]:
        assert code not in codes and en and isinstance(aliases, list) and tasks
        codes.add(code)
        assert abs(sum(t[2] for t in tasks) - 100) < 0.5, code  # 占比是百分数，合计 100
        assert all(t[1] > 0 and t[3] in (0, 1, 2) for t in tasks), code
