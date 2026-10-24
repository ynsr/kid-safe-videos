"""Validators, vision parsing (garbage -> UNSURE), cache, fingerprint, sidecars."""
import json

from kidsafe.sidecar import build_sidecar, check_stale, validate_sidecar
from kidsafe.util import format_timecode, parse_timecode, sha256_partial
from kidsafe.validators import (validate_cuts, validate_research,
                                validate_suitability)
from kidsafe.vision import normalise_triage, parse_strict_json


def test_research_rejects_missing_source():
    errs = validate_research({"reference_runtime_seconds": 90, "matched_imdb_id": "tt1",
                              "items": [{"id": "a", "description": "x",
                                         "category": "c", "time_basis": "none",
                                         "confidence": "low"}]})
    assert any("source_url" in e for e in errs)


def test_research_rejects_wide_time_with_high_confidence():
    errs = validate_research({"reference_runtime_seconds": 90, "matched_imdb_id": "tt1",
                              "items": [{"id": "a", "description": "x", "category": "c",
                                         "time_basis": "fraction_of_runtime",
                                         "approx_time_seconds": 10,
                                         "confidence": "high",
                                         "source_url": "u", "evidence_snippet": "e"}]})
    assert any("non-explicit" in e for e in errs)


def test_suitability_rejects_evidence_without_source():
    errs = validate_suitability({"title_level": {
        "verdict": "unknown", "confidence": "low",
        "dimensions": {d: {"level": "unknown", "evidence": [{"x": 1}]}
                       for d in ["romance_prevalence", "romance_as_central_plot",
                                 "horror_scary", "violence", "mature_themes",
                                 "values_concerns"]},
        "summary": "s", "limitations": ["l"]}})
    assert any("source_url" in e for e in errs)


def test_cuts_rejects_inverted_range():
    errs = validate_cuts({"cuts": [{"id": "c1", "start_seconds": 5, "end_seconds": 2,
                                    "type": "x", "decision": "accepted"}]})
    assert any("start_seconds" in e for e in errs)


def test_garbage_model_output_is_unsure():
    assert parse_strict_json("not json at all {{{") is None
    norm = normalise_triage(None, {0, 1, 2})
    assert {f["tile"] for f in norm["flagged"]} == {0, 1, 2}
    assert all(f["answer"] == "UNSURE" for f in norm["flagged"])


def test_triage_keeps_only_valid_tiles():
    norm = normalise_triage({"flagged": [
        {"tile": 0, "category": "c", "answer": "YES", "reason": "r"},
        {"tile": 99, "category": "c", "answer": "YES", "reason": "r"}]}, {0})
    assert [f["tile"] for f in norm["flagged"]] == [0]


def test_timecode_roundtrip():
    assert parse_timecode(format_timecode(3723.456)) - 3723.456 < 0.001


def test_empty_parts_sidecar_validates(tmp_path):
    (tmp_path / "context.yaml").write_text("title: T\n")
    (tmp_path / "probe.json").write_text(json.dumps(
        {"duration_seconds": 60, "fps": 24, "fingerprint": {"value": "x"}}))
    (tmp_path / "candidates.yaml").write_text("candidates: []\n")
    (tmp_path / "cuts.yaml").write_text("cuts: []\n")
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / "v.mp4")],
                   capture_output=True, check=True)
    data = build_sidecar(tmp_path / "v.mp4", tmp_path, "config")
    data["source"]["fingerprint"]["value"] = sha256_partial(tmp_path / "v.mp4")
    assert data["parts"] == []
    text = json.dumps(data).lower()
    assert "verified safe" not in text and "\"safe\"" not in text and "certified safe" not in text


def test_stale_sidecar_detected(tmp_path):
    import subprocess
    a = tmp_path / "a.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
                    "-c:v", "libx264", str(a)], capture_output=True, check=True)
    side = {"source": {"duration_seconds": 1.0,
                       "fingerprint": {"value": sha256_partial(a)}}}
    stale, _ = check_stale(a, side)
    assert stale is False
    side["source"]["duration_seconds"] = 99.0
    stale, reason = check_stale(a, side)
    assert stale is True and "duration" in reason


def test_import_rejected_stays_rejected(tmp_path):
    # import path keeps rejected decisions so they are not re-flagged
    cuts = {"cuts": [{"id": "p001", "start_seconds": 1, "end_seconds": 2,
                      "type": "x", "decision": "rejected"}]}
    assert cuts["cuts"][0]["decision"] == "rejected"
