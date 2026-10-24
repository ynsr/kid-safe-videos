"""Time scaling, window computation, grid tile mapping, dedupe, keyframes, merge."""
from kidsafe.align import apply_landmarks, build_windows, compute_scale
from kidsafe.cut import invert_ranges, snap_outward
from kidsafe.frames import block_hash, dedupe, hamming
from kidsafe.grid import build_grids
from kidsafe.merge import merge_ranges
from kidsafe.cut_burden import burden


def pipe():
    return {"localise": {"window_minutes_explicit_time": 4, "window_minutes_wide": 8,
                         "window_fraction_plot_position": 0.10},
            "padding_seconds": 1.0}


def test_scale_warns_beyond_5pct():
    scale, warn = compute_scale(100.0, 90.0)
    assert abs(scale - 100 / 90) < 1e-9 and warn


def test_scale_quiet_within_5pct():
    scale, warn = compute_scale(100.0, 102.0)
    assert warn is None


def test_explicit_window():
    research = {"reference_runtime_seconds": 100.0, "items": [
        {"id": "r1", "category": "romantic_affection", "time_basis": "explicit",
         "approx_time_seconds": 50.0}]}
    windows, _s, _w = build_windows(research, 100.0, pipe())
    assert windows[0]["start"] == 0.0 or windows[0]["start"] >= 0.0
    assert windows[0]["end"] <= 100.0


def test_fraction_window():
    research = {"reference_runtime_seconds": 200.0, "items": [
        {"id": "r1", "category": "x", "time_basis": "fraction_of_runtime",
         "approx_time_seconds": 100.0}]}
    windows, _s, _w = build_windows(research, 200.0, pipe())
    assert windows[0]["end"] - windows[0]["start"] == 40.0  # 2 * 0.10 * 200


def test_none_basis_covers_whole_movie_lowest_priority():
    research = {"reference_runtime_seconds": 100.0, "items": [
        {"id": "r1", "category": "x", "time_basis": "none", "approx_time_seconds": None}]}
    windows, _s, _w = build_windows(research, 100.0, pipe())
    assert (windows[0]["start"], windows[0]["end"], windows[0]["priority"]) == (0.0, 100.0, 3)


def test_landmark_piecewise():
    lm = [{"guide_time": 0, "local_time": 10}, {"guide_time": 100, "local_time": 120}]
    assert apply_landmarks(50, lm) == 65.0


def test_dedupe_drops_identical(tmp_path):
    from PIL import Image
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(a)
    Image.new("RGB", (32, 32), (10, 20, 30)).save(b)
    kept = dedupe([(a, 0.0), (b, 1.0)])
    assert len(kept) == 1 and b.exists() is False


def test_grid_mapping_and_overlap(tmp_path):
    from PIL import Image
    frames = []
    for i in range(5):
        p = tmp_path / f"f_{float(i):08.3f}.jpg"
        Image.new("RGB", (64, 36), (i * 10, 0, 0)).save(p)
        frames.append((p, float(i)))
    grids = build_grids(frames, "2x2", tmp_path / "g")
    assert grids[0]["tiles"][0] == 0.0
    # overlap of one tile: second grid starts at frame 3
    assert grids[1]["tiles"][0] == 3.0


def test_snap_outward():
    kf = [0.0, 5.0, 10.0, 15.0]
    s, e, extra, _w = snap_outward(6.0, 9.0, kf)
    assert (s, e) == (5.0, 10.0) and extra == 2.0


def test_invert_ranges():
    assert invert_ranges([(5.0, 10.0)], 20.0) == [(0.0, 5.0), (10.0, 20.0)]


def test_merge_close_ranges():
    out = merge_ranges([
        {"id": "a", "start": 0.0, "end": 5.0, "origin": "sweep"},
        {"id": "b", "start": 8.0, "end": 10.0, "origin": "research"}], min_keep_gap=8.0)
    assert len(out) == 1 and out[0]["end"] == 10.0


def test_hamming_zero_for_same():
    from PIL import Image
    im = Image.new("RGB", (16, 16), (5, 5, 5))
    assert hamming(block_hash(im), block_hash(im)) == 0


def test_burden_thresholds():
    rules = {"family_values": {"thresholds": {
        "max_percent_removed": 15, "max_cuts_per_10min": 3,
        "max_romance_scene_fraction": 0.10}}}
    cands = [{"start": 0, "end": 40, "category": "romantic_affection", "status": "pending"}]
    b = burden(cands, 100.0, rules)
    assert b["verdict"] == "not_recommended_after_cuts"
    assert any("38" in r or "40" in r or "removed" in r for r in b["reasons"])
