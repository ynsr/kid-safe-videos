"""Review UI backend endpoints (Flask test client)."""
import json
from pathlib import Path

import pytest

flask = pytest.importorskip("flask")


@pytest.fixture()
def app_ctx(tmp_path, monkeypatch):
    v = tmp_path / "v.mp4"
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=4:size=64x64:rate=5",
                    "-c:v", "libx264", "-g", "5", "-pix_fmt", "yuv420p", str(v)], capture_output=True, check=True)
    wd = tmp_path / "w1"
    wd.mkdir()
    from kidsafe.probe import probe_and_cache
    probe_and_cache(v, wd)
    (wd / "context.yaml").write_text(f"video: {v}\ntitle: t\n")
    (wd / "candidates.yaml").write_text(
        "candidates: [{id: c001, start: 1.0, end: 2.0, category: romantic_affection, "
        "severity: high, confidence: high, origin: sweep, description: d}]\n")
    import kidsafe.review_app as ra
    monkeypatch.setattr(ra, "WORK_ROOT", tmp_path)
    monkeypatch.setattr(ra, "CONFIG_DIR", Path("config"))
    ra.app.config["TESTING"] = True
    return ra.app.test_client(), "w1"


def test_state_lists_candidates(app_ctx):
    client, wid = app_ctx
    r = client.get(f"/api/state?id={wid}")
    assert r.status_code == 200
    assert r.get_json()["candidates"][0]["id"] == "c001"


def test_decide_persists_and_next(app_ctx):
    client, wid = app_ctx
    r = client.post(f"/api/decide?id={wid}",
                    json={"id": "c001", "decision": "rejected"})
    assert r.get_json()["ok"] is True
    st = client.get(f"/api/state?id={wid}").get_json()
    assert st["candidates"][0]["decision"] == "rejected"
    assert client.get(f"/api/next?id={wid}").get_json()["id"] is None


def test_snap_endpoint(app_ctx):
    client, wid = app_ctx
    r = client.get(f"/api/snap?id={wid}&start=0.5&end=1.0")
    assert r.status_code == 200
    j = r.get_json()
    assert j["snapped"][0] <= 0.5 and j["snapped"][1] >= 1.0
