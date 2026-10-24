"""Localise runner with a stubbed vision backend (no model needed)."""
from pathlib import Path

import kidsafe.localise as loc
import kidsafe.sweep as sweep


def _setup_work(tmp_path):
    import subprocess
    v = tmp_path / "synth.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                    "-i", "testsrc=duration=30:size=128x128:rate=10",
                    "-c:v", "libx264", "-g", "10", "-pix_fmt", "yuv420p", str(v)],
                   capture_output=True, check=True)
    wd = tmp_path / "w"
    from kidsafe.probe import probe_and_cache
    probe_and_cache(v, wd)
    (wd / "context.yaml").write_text(f"video: {v}\ntitle: T\n")
    (wd / "research.yaml").write_text(
        "reference_runtime_seconds: 30.0\nmatched_imdb_id: tt0000001\n"
        "items: [{id: r1, description: 'a red moment', category: test_scene, "
        "approx_time_seconds: 10.0, time_basis: explicit, source_url: http://x, "
        "evidence_snippet: e, confidence: low}]\n")
    (wd / "windows.yaml").write_text(
        "scale: 1.0\nwarning: null\n"
        "windows: [{research_id: r1, category: test_scene, start: 6.0, end: 14.0, priority: 1}]\n")
    return v, wd


def _fake_query_grid(grid_image, tiles, template, subs, role, *a, **k):
    if role == "frame_triage":
        # flag every tile in grids covering the middle of the window
        mid = sorted(tiles.values())[len(tiles) // 2]
        if 8.0 <= mid <= 12.0:
            return {"parsed": {"flagged": [
                {"tile": t, "category": "test_scene", "answer": "YES", "reason": "stub"}
                for t in tiles]}, "model": "stub", "role": role}
        return {"parsed": {"flagged": []}, "model": "stub", "role": role}
    # grid_refine: return full span
    ts = sorted(tiles)
    return {"parsed": {"first_tile": ts[0], "last_tile": ts[-1],
                       "answer": "YES", "reason": "stub"},
            "model": "stub", "role": role}


def test_localise_end_to_end_with_stubbed_vision(tmp_path, monkeypatch):
    v, wd = _setup_work(tmp_path)
    monkeypatch.setattr(loc.vision_mod, "query_grid", _fake_query_grid)
    rec = loc.localise_title(v, wd, Path("config"), Path("prompts"))
    assert rec["windows"] == 1
    assert len(rec["hits"]) == 1
    hit = rec["hits"][0]
    assert 6.0 <= hit["start"] <= hit["end"] <= 14.0
    # no timestamps invented by stub: start/end must be real extracted frame times
    times = set()
    for fp in (wd / "frames" / "loc_r1").glob("f_*.jpg"):
        times.add(round(float(fp.stem[2:]), 3))
    assert hit["start"] in times and hit["end"] in times


def test_localise_garbage_vision_widens_not_drops(tmp_path, monkeypatch):
    v, wd = _setup_work(tmp_path)

    def _garbage(*a, **k):
        return {"parsed": {"flagged": [
            {"tile": t, "category": "unknown", "answer": "UNSURE",
             "reason": "unparseable model output"} for t in (0, 1)]},
            "model": "stub", "role": a[4] if len(a) > 4 else "x"}
    monkeypatch.setattr(loc.vision_mod, "query_grid", _garbage)
    rec = loc.localise_title(v, wd, Path("config"), Path("prompts"))
    # UNSURE must ADD flags, never silently drop the window
    assert len(rec["hits"]) >= 1


def test_sweep_stubbed_vision_and_skip(tmp_path, monkeypatch):
    v, wd = _setup_work(tmp_path)
    monkeypatch.setattr(sweep.vision_mod, "query_grid", _fake_query_grid)
    rec = sweep.sweep_title(v, wd, Path("config"), Path("prompts"))
    assert rec["status"] == "done"
    assert all("time" in h and "category" in h for h in rec["hits"])
    rec2 = sweep.sweep_title(v, wd, Path("config"), Path("prompts"), skip=True)
    assert rec2 == {"status": "skipped", "hits": []}


def test_normalise_refine_contract():
    from kidsafe.vision import normalise_refine
    ok = normalise_refine({"first_tile": 5, "last_tile": 2, "answer": "yes",
                           "reason": "r"}, set(range(9)))
    assert (ok["first_tile"], ok["last_tile"]) == (2, 5)
    bad = normalise_refine({"first_tile": 99, "answer": "NO", "reason": ""}, {0, 1})
    assert bad["first_tile"] is None and bad["answer"] == "NO"
    garbage = normalise_refine(None, {0})
    assert garbage["answer"] == "UNSURE"
