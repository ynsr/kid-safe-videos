"""YAML schema validators. Agent-written files must pass before use."""
from __future__ import annotations

import argparse
from pathlib import Path

from .util import load_yaml

TIME_FIELDS = {"explicit", "fraction_of_runtime", "plot_position", "none"}

SUITABILITY_DIMS = {"romance_prevalence", "romance_as_central_plot", "horror_scary",
                    "violence", "mature_themes", "values_concerns"}
DIM_LEVELS = {"none", "minor", "moderate", "major", "unknown"}
VERDICTS = {"recommended", "recommended_after_cuts", "not_recommended", "unknown"}


def validate_research(data: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["research.yaml must be a mapping"]
    if not data.get("reference_runtime_seconds"):
        errs.append("reference_runtime_seconds is required")
    if not data.get("matched_imdb_id"):
        errs.append("matched_imdb_id is required")
    items = data.get("items")
    if not isinstance(items, list):
        return errs + ["items must be a list"]
    for i, it in enumerate(items):
        tag = f"items[{i}]"
        if not isinstance(it, dict):
            errs.append(f"{tag} must be a mapping")
            continue
        for f in ("id", "description", "category"):
            if not it.get(f):
                errs.append(f"{tag}.{f} is required")
        if not it.get("source_url"):
            errs.append(f"{tag}.source_url is required (no source means no entry)")
        if not it.get("evidence_snippet"):
            errs.append(f"{tag}.evidence_snippet is required")
        tb = it.get("time_basis", "none")
        if tb not in TIME_FIELDS:
            errs.append(f"{tag}.time_basis must be one of {sorted(TIME_FIELDS)}")
        t = it.get("approx_time_seconds")
        if t is not None and (not isinstance(t, (int, float)) or t < 0):
            errs.append(f"{tag}.approx_time_seconds must be >= 0 or null")
        if it.get("confidence") not in ("low", "med", "high"):
            errs.append(f"{tag}.confidence must be low|med|high")
        if tb != "explicit" and t is not None and it.get("confidence") != "low":
            errs.append(f"{tag}: non-explicit time_basis must carry confidence low")
    return errs


def validate_suitability(data: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["suitability.yaml must be a mapping"]
    tl = data.get("title_level")
    if not isinstance(tl, dict):
        return errs + ["title_level mapping is required"]
    if tl.get("verdict") not in VERDICTS:
        errs.append(f"title_level.verdict must be one of {sorted(VERDICTS)}")
    if tl.get("confidence") not in ("low", "med", "high"):
        errs.append("title_level.confidence must be low|med|high")
    dims = tl.get("dimensions") or {}
    for name in SUITABILITY_DIMS:
        d = dims.get(name)
        if not isinstance(d, dict):
            errs.append(f"dimensions.{name} mapping is required")
            continue
        if d.get("level") not in DIM_LEVELS:
            errs.append(f"dimensions.{name}.level must be one of {sorted(DIM_LEVELS)}")
        for e in d.get("evidence") or []:
            if not isinstance(e, dict) or not e.get("source_url"):
                errs.append(f"dimensions.{name}.evidence entries need source_url")
    if not tl.get("summary"):
        errs.append("title_level.summary is required (max 5 sentences)")
    if not tl.get("limitations"):
        errs.append("title_level.limitations is required")
    return errs


def validate_cuts(data: dict, duration: float | None = None) -> list[str]:
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["cuts.yaml must be a mapping"]
    cuts = data.get("cuts")
    if not isinstance(cuts, list):
        return errs + ["cuts must be a list"]
    for i, c in enumerate(cuts):
        tag = f"cuts[{i}]"
        if not isinstance(c, dict):
            errs.append(f"{tag} must be a mapping")
            continue
        for f in ("id", "start_seconds", "end_seconds", "type", "decision"):
            if c.get(f) is None:
                errs.append(f"{tag}.{f} is required")
        s, e = c.get("start_seconds"), c.get("end_seconds")
        if isinstance(s, (int, float)) and isinstance(e, (int, float)) and not s < e:
            errs.append(f"{tag}: start_seconds must be < end_seconds")
        if duration is not None and isinstance(e, (int, float)) and e > duration:
            errs.append(f"{tag}: end_seconds beyond duration")
        if c.get("decision") not in ("accepted", "rejected", "corrected", "pending"):
            errs.append(f"{tag}.decision must be accepted|rejected|corrected|pending")
    return errs


def _cmd(name: str, fn, extra_args: bool = False) -> None:
    ap = argparse.ArgumentParser(description=f"Validate {name}")
    ap.add_argument("path", type=Path)
    if extra_args:
        ap.add_argument("--duration", type=float, default=None)
    args = ap.parse_args()
    data = load_yaml(args.path)
    errs = fn(data, args.duration) if extra_args else fn(data)
    if errs:
        print("\n".join(f"ERROR: {e}" for e in errs))
        raise SystemExit(1)
    print("OK")


def main_validate_research() -> None:
    _cmd("research.yaml", validate_research)


def main_validate_suitability() -> None:
    _cmd("suitability.yaml", validate_suitability)


def main_validate_cuts() -> None:
    _cmd("cuts.yaml", validate_cuts, extra_args=True)
