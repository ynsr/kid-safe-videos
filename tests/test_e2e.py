"""End-to-end on a synthetic video: stream-copy-only cutting + verify + sidecar.

Builds a 12s testsrc video with frequent keyframes, cuts 4-6s losslessly,
checks output duration, stream preservation, and the sidecar build block.
Round trip: delete work dir, import-sidecar, get the same cuts.
"""
import json
import subprocess
from pathlib import Path

import pytest

from kidsafe.cut import build_cut_plan, invert_ranges, run_cut
from kidsafe.probe import extract_keyframes, probe_and_cache
from kidsafe.sidecar import build_sidecar, validate_sidecar
from kidsafe.util import load_yaml, sha256_partial
from kidsafe.verify import verify_build


@pytest.fixture()
def synth(tmp_path):
    v = tmp_path / "synth.mp4"
    # frequent keyframes (every ~1s) so snapping is tight
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                    "-i", "testsrc=duration=12:size=128x128:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
                    "-c:v", "libx264", "-g", "10", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(v)],
                   capture_output=True, check=True)
    wd = tmp_path / "work"
    probe = probe_and_cache(v, wd)
    (wd / "context.yaml").write_text(f"video: {v}\ntitle: synth\n")
    (wd / "candidates.yaml").write_text(
        "candidates: [{id: c001, start: 4.0, end: 6.0, category: test_scene, "
        "severity: medium, confidence: high, origin: manual, description: 'synthetic test segment'}]\n")
    (wd / "cuts.yaml").write_text(
        "cuts: [{id: c001, start_seconds: 4.0, end_seconds: 6.0, "
        "type: test_scene, decision: accepted, description: 'synthetic test segment for cut path'}]\n")
    return v, wd, probe


def _kfs(wd):
    kf = json.loads((wd / "keyframes.json").read_text())
    return kf["keyframes"] if isinstance(kf, dict) else kf


def test_probe_reports_audio_tracks(synth):
    _v, _wd, probe = synth
    kinds = [s["type"] for s in probe["streams"]]
    assert "video" in kinds and "audio" in kinds


def test_keyframes_cover_timeline(synth):
    _v, wd, _p = synth
    assert len(_kfs(wd)) >= 5


def test_e2e_lossless_cut_verify_sidecar(synth, tmp_path):
    v, wd, probe = synth
    dur = float(probe["duration_seconds"])
    kfs = _kfs(wd)
    out = tmp_path / "final.mp4"
    rep = run_cut(v, wd / "cuts.yaml", kfs, dur, out)
    assert out.exists()
    # pure stream copy: same codecs, no re-encode filter in path (concat demuxer)
    removed = sum(c[1] - c[0] for c in
                  [(c["snapped"][0], c["snapped"][1]) for c in rep["snapped_cuts"]])
    ver = verify_build(v, out, removed)
    assert ver["ok"], ver
    assert ver["streams_preserved"] is True
    # sidecar with build block
    (wd / "verify.yaml").write_text(
        __import__("yaml").safe_dump(ver))
    data = build_sidecar(v, wd, "config")
    data["source"]["fingerprint"]["value"] = sha256_partial(v)
    data["build"] = ver
    assert validate_sidecar(data) == []
    assert data["summary"]["accepted_count"] == 1


def test_e2e_roundtrip_import_sidecar(synth, tmp_path):
    import shutil
    v, wd, probe = synth
    dur = float(probe["duration_seconds"])
    kfs = _kfs(wd)
    out = tmp_path / "final.mp4"
    run_cut(v, wd / "cuts.yaml", kfs, dur, out)
    data = build_sidecar(v, wd, "config")
    data["source"]["fingerprint"]["value"] = sha256_partial(v)
    side = tmp_path / "synth-inappropriate-parts.yml"
    side.write_text(__import__("yaml").safe_dump(data))
    # delete work dir, re-import
    shutil.rmtree(wd)
    from kidsafe.sidecar import check_stale
    stale, _ = check_stale(v, __import__("yaml").safe_load(side.read_text()))
    assert stale is False
    loaded = __import__("yaml").safe_load(side.read_text())
    assert [(p["id"], p["decision"]) for p in loaded["parts"]] == [("c001", "accepted")]
