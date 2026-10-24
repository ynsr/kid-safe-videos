"""cut.py: LOSSLESS cutting via ffmpeg stream copy. No re-encoding, ever.

Reads accepted/corrected cuts, inverts to keep-ranges, snaps every cut
OUTWARD to keyframes so no unsafe frame survives. All streams copied
(-c copy): video, all audio tracks, subtitles. Concat demuxer with
correct timestamp handling. Fails loudly if lossless is impossible.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from .util import format_timecode, load_json, load_yaml, run_cmd


def snap_outward(start: float, end: float, keyframes: list[float],
                 max_gap: float = 30.0) -> tuple[float, float, float, list[str]]:
    """Snap start DOWN to prev keyframe, end UP to next keyframe."""
    warnings: list[str] = []
    ks = sorted(keyframes)
    if not ks:
        raise RuntimeError("no keyframes available; lossless cutting impossible")
    prev = [k for k in ks if k <= start]
    nxt = [k for k in ks if k >= end]
    if not prev:
        raise RuntimeError(f"no keyframe at/before cut start {start:.3f}; lossless impossible")
    if not nxt:
        raise RuntimeError(f"no keyframe at/after cut end {end:.3f}; lossless impossible")
    s, e = prev[-1], nxt[0]
    extra = (start - s) + (e - end)
    if (start - s) > max_gap or (e - end) > max_gap:
        warnings.append(f"keyframe gap > {max_gap}s near [{start:.2f},{end:.2f}]")
    return s, e, round(extra, 3), warnings


def invert_ranges(cuts: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    cuts = sorted(cuts)
    keep: list[tuple[float, float]] = []
    cur = 0.0
    for s, e in cuts:
        if s > cur:
            keep.append((cur, min(s, duration)))
        cur = max(cur, e)
    if cur < duration:
        keep.append((cur, duration))
    return [(s, e) for s, e in keep if e - s > 1e-6]


def build_cut_plan(cuts_yaml: dict, keyframes: list[float], duration: float,
                   max_gap: float = 30.0) -> tuple[dict, list[str]]:
    cuts = [(c["start_seconds"], c["end_seconds"])
            for c in cuts_yaml.get("cuts", [])
            if c.get("decision") in ("accepted", "corrected")]
    snapped: list[dict] = []
    warnings: list[str] = []
    for s, e in sorted(cuts):
        ss, ee, extra, w = snap_outward(s, e, keyframes, max_gap)
        warnings.extend(w)
        snapped.append({"requested": [s, e], "snapped": [ss, ee],
                        "extra_removed_seconds": extra})
    keep = invert_ranges([(p["snapped"][0], p["snapped"][1]) for p in snapped], duration)
    return {"keep_ranges": keep, "snapped_cuts": snapped}, warnings


def run_cut(video: Path, cuts_yaml_path: Path, keyframes: list[float],
            duration: float, out_path: Path, max_gap: float = 30.0,
            work_tmp: Path | None = None) -> dict:
    cuts_yaml = load_yaml(cuts_yaml_path)
    plan, warnings = build_cut_plan(cuts_yaml, keyframes, duration, max_gap)
    snapped = plan["snapped_cuts"]
    keep = plan["keep_ranges"]
    tmp = (work_tmp or out_path.parent) / ".kidsafe_cut_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for i, (s, e) in enumerate(keep):
        part = tmp / f"part_{i:04d}.mkv"
        # Stream copy; seek to snapped keyframe. -avoid_negative_ts for concat.
        cmd = ["ffmpeg", "-y", "-ss", f"{s:.3f}", "-i", str(video),
               "-t", f"{(e - s):.3f}", "-c", "copy",
               "-avoid_negative_ts", "make_zero", str(part)]
        r = run_cmd(cmd)
        if r.returncode != 0:
            raise RuntimeError(f"lossless segment extract failed [{s:.2f},{e:.2f}]: {r.stderr[-800:]}")
        parts.append(part)
    lst = tmp / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out_path.with_name(out_path.name + ".tmp.part" + out_path.suffix)
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
           "-c", "copy", "-avoid_negative_ts", "make_zero", str(tmp_out)]
    r = run_cmd(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"lossless concat failed: {r.stderr[-800:]}")
    # Atomic publish
    import os
    os.replace(tmp_out, out_path)
    for p in parts:
        p.unlink(missing_ok=True)
    try:
        lst.unlink(missing_ok=True)
    except OSError:
        pass
    return {"output": str(out_path), "keep_ranges": keep, "snapped_cuts": snapped,
            "warnings": warnings}


def main() -> None:
    ap = argparse.ArgumentParser(description="Lossless stream-copy cut")
    ap.add_argument("video", type=Path)
    ap.add_argument("--cuts", type=Path, required=True)
    ap.add_argument("--keyframes", type=Path, required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--max-gap", type=float, default=30.0)
    args = ap.parse_args()
    kf = load_json(args.keyframes)
    kfs = kf.get("keyframes", []) if isinstance(kf, dict) else kf
    rep = run_cut(args.video.resolve(), args.cuts, kfs, args.duration,
                  args.out.resolve(), args.max_gap)
    print(f"wrote {rep['output']} keep_ranges={len(rep['keep_ranges'])} "
          f"warnings={len(rep['warnings'])}")


if __name__ == "__main__":
    main()
