"""sidecar.py: build/validate/reuse <stem>-inappropriate-parts.yml.

The single per-video record for audit and reuse. The agent NEVER writes it
by hand. Generated deterministically from candidates.yaml + cuts.yaml +
probe data. There is NO separate audit file.
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from . import __version__
from .config import load_config
from .util import (format_timecode, load_yaml, sha256_full, sha256_partial,
                   write_yaml_atomic)

SCHEMA_VERSION = 1


def sidecar_name(video: Path) -> str:
    return video.stem + "-inappropriate-parts.yml"


def build_sidecar(video: Path, work_dir: Path, config_dir: Path,
                  verdict: str | None = None) -> dict:
    from .config import load_config as _lc
    cfg = _lc(config_dir)
    probe = load_yaml(work_dir / "probe.json")
    cands = (load_yaml(work_dir / "candidates.yaml")
             if (work_dir / "candidates.yaml").exists() else {"candidates": {}})
    cuts_f = (load_yaml(work_dir / "cuts.yaml")
              if (work_dir / "cuts.yaml").exists() else {"cuts": []})
    decisions = {c.get("id"): c for c in cuts_f.get("cuts", [])}
    suit = (load_yaml(work_dir / "suitability.yaml")
            if (work_dir / "suitability.yaml").exists() else {})
    verify = (load_yaml(work_dir / "verify.yaml")
              if (work_dir / "verify.yaml").exists() else None)
    max_chars = int((((cfg.rules.get("sidecar", {}) or {}).get("max_description_chars")) or 160))

    parts: list[dict] = []
    for c in cands.get("candidates", []):
        d = decisions.get(c.get("id"), {})
        decision = d.get("decision", c.get("status", "pending"))
        if decision == "pending":
            decision = "rejected" if False else decision  # keep pending visible
        s = float(d.get("start_seconds", c["start"]))
        e = float(d.get("end_seconds", c["end"]))
        parts.append({
            "id": c.get("id"), "start_seconds": round(s, 3), "end_seconds": round(e, 3),
            "start_timecode": format_timecode(s), "end_timecode": format_timecode(e),
            "type": d.get("type", c.get("category")), "severity": c.get("severity", "medium"),
            "description": str(d.get("description", c.get("description", "")))[:max_chars],
            "origin": c.get("origin"), "confidence": d.get("confidence", c.get("confidence")),
            "source_url": c.get("source_url"), "evidence": c.get("evidence"),
            "decision": decision,
            "proposed": {"start_seconds": round(float(c["start"]), 3),
                         "end_seconds": round(float(c["end"]), 3)},
            "cut": d.get("cut"),
            "note": d.get("note"),
        })
    accepted = [p for p in parts if p["decision"] in ("accepted", "corrected")]
    removed = sum(p["end_seconds"] - p["start_seconds"] for p in accepted)
    dur = float(probe.get("duration_seconds", 0) or 0)
    tl = (suit.get("title_level") or {})
    sidecar = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": f"kidsafe {__version__}",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "filename": video.name, "relative_path": video.name,
            "duration_seconds": dur, "fps": probe.get("fps"),
            "size_bytes": video.stat().st_size if video.exists() else probe.get("size_bytes"),
            "fingerprint": {"algo": "sha256-partial",
                            "value": (probe.get("fingerprint") or {}).get("value")},
            "full_sha256": None,
            "title": (load_yaml(work_dir / "context.yaml").get("title")
                      if (work_dir / "context.yaml").exists() else video.stem),
            "year": None, "imdb_id": None, "season": None, "episode": None,
        },
        "analysis": {
            "status": "analysed_reviewed" if any(
                d.get("decision") in ("accepted", "rejected", "corrected")
                for d in decisions.values()) else "analysed_unreviewed",
            "rules_version": cfg.rules.get("version", 1),
            "passes": ["research", "localise", "sweep", "manual"],
            "models": [],
            "not_analysed": ["audio", "dialogue", "music", "video_motion"],
            "reviewed_by": "human" if decisions else "none",
            "reviewed_at": None,
        },
        "parts": parts,
        "summary": {"accepted_count": len(accepted),
                    "total_removed_seconds": round(removed, 3),
                    "percent_removed": round(100 * removed / dur, 2) if dur else 0.0,
                    "suitability_verdict": verdict or tl.get("verdict")},
        "build": verify,
    }
    return sidecar


def validate_sidecar(data: dict, max_chars: int = 160) -> list[str]:
    errs: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version must be {SCHEMA_VERSION}")
    src = data.get("source") or {}
    for f in ("filename", "duration_seconds", "fingerprint"):
        if src.get(f) is None:
            errs.append(f"source.{f} is required")
    parts = data.get("parts")
    if not isinstance(parts, list):
        return errs + ["parts must be a list (may be empty)"]
    seen: list[tuple[float, float]] = []
    dur = float(src.get("duration_seconds") or 0)
    for i, p in enumerate(parts):
        tag = f"parts[{i}]"
        for f in ("id", "start_seconds", "end_seconds", "type", "decision"):
            if p.get(f) is None:
                errs.append(f"{tag}.{f} is required")
        s, e = p.get("start_seconds"), p.get("end_seconds")
        if isinstance(s, (int, float)) and isinstance(e, (int, float)):
            if not s < e:
                errs.append(f"{tag}: start must be < end")
            if dur and e > dur + 0.01:
                errs.append(f"{tag}: end beyond duration")
            for os_, oe in seen:
                if s < oe and os_ < e and p.get("decision") in ("accepted", "corrected"):
                    errs.append(f"{tag}: overlaps another accepted part")
            if p.get("decision") in ("accepted", "corrected"):
                seen.append((s, e))
        if len(str(p.get("description", ""))) > max_chars:
            errs.append(f"{tag}.description exceeds {max_chars} chars")
        if not str(p.get("description", "")).strip():
            errs.append(f"{tag}.description must be non-empty neutral text")
    return errs


def check_stale(video: Path, sidecar: dict, full_hash: bool = False) -> tuple[bool, str]:
    src = sidecar.get("source", {}) or {}
    fp = (src.get("fingerprint") or {}).get("value")
    cur = sha256_partial(video)
    if fp != cur:
        return True, "partial fingerprint mismatch"
    if abs(float(src.get("duration_seconds", 0)) - _duration(video)) > 0.5:
        return True, "duration differs by more than 0.5s"
    if full_hash and src.get("full_sha256"):
        if sha256_full(video) != src["full_sha256"]:
            return True, "full SHA-256 mismatch"
    return False, "ok"


def _duration(video: Path) -> float:
    import json, subprocess
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_format", str(video)],
                       capture_output=True, text=True, check=False)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001
        return 0.0


def write_sidecar(video: Path, work_dir: Path, config_dir: Path,
                  dest: Path | None = None,
                  verdict: str | None = None) -> Path:
    data = build_sidecar(video, work_dir, config_dir, verdict)
    errs = validate_sidecar(data)
    if errs:
        raise RuntimeError("sidecar validation failed: " + "; ".join(errs))
    cfg = load_config(config_dir)
    from .util import dump_yaml, atomic_write_text
    text = dump_yaml(data)
    if dest is not None:
        atomic_write_text(dest, text)
        return dest
    return write_default_locations(video, work_dir, config_dir, text)


def write_default_locations(video: Path, work_dir: Path, config_dir: Path,
                            text: str) -> Path:
    from .util import atomic_write_text
    cfg = load_config(config_dir)
    loc = ((cfg.rules.get("sidecar", {}) or {}).get("location") or "both")
    outs: list[Path] = []
    if loc in ("output", "both"):
        out_root = ((cfg.rules.get("library", {}) or {}).get("output_root") or "")
        if out_root:
            # mirrored path resolution happens in CLI; here: work/output
            p = work_dir / "output" / sidecar_name(video)
            atomic_write_text(p, text)
            outs.append(p)
    if loc in ("source", "both"):
        p = video.parent / sidecar_name(video)
        atomic_write_text(p, text)
        outs.append(p)
    # always keep a work copy
    w = work_dir / sidecar_name(video)
    from .util import atomic_write_text as _w
    _w(w, text)
    outs.append(w)
    return outs[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Build/validate a sidecar file")
    ap.add_argument("video", type=Path)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=Path("config"))
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    p = write_sidecar(args.video.resolve(), args.work_dir, args.config, args.out)
    print(f"sidecar -> {p}")


if __name__ == "__main__":
    main()
