"""用 node 跑 functions/api/search.js 的模拟测试（不联网）：Google 被拦 -> Bing -> GDELT 的切换、分类、去重。"""
import shutil, subprocess
from pathlib import Path
import pytest

HERE = Path(__file__).parent

@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_search_fallback():
    r = subprocess.run(["node", str(HERE / "search_fallback.mjs")], capture_output=True, text=True, cwd=HERE)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL PASS" in r.stdout
