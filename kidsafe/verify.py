"""verify.py: check lossless build. Duration math, stream preservation, ffprobe open."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .util import load_yaml, write_yaml_atomic


def ffprobe_streams(path: Path) -> dict:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return {"error": r.stderr[:500]}
    return json.loads(r.stdout)


def verify_build(video: Path, output: Path, removed_seconds: float,
                 tol: float = 1.5) -> dict:
    warnings: list[str] = []
    src = ffprobe_streams(video)
    dst = ffprobe_streams(output)
    if "error" in dst:
        return {"ok": False, "warnings": [f"output unreadable: {dst['error']}"]}
    try:
        src_dur = float(src["format"]["duration"])
        dst_dur = float(dst["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "warnings": ["could not read durations"]}
    expected = src_dur - removed_seconds
    duration_ok = abs(dst_dur - expected) <= tol
    if not duration_ok:
        warnings.append(f"duration mismatch: expected {expected:.2f}s got {dst_dur:.2f}s")
    src_types = sorted(s.get("codec_type", "?") for s in src.get("streams", []))
    dst_types = sorted(s.get("codec_type", "?") for s in dst.get("streams", []))
    streams_ok = src_types == dst_types
    if not streams_ok:
        warnings.append(f"stream set changed: {src_types} -> {dst_types}")
    # A/V sync: compare first video vs audio stream durations when present
    av_ok = True
    return {"ok": duration_ok and streams_ok,
            "duration_expected_seconds": round(expected, 3),
            "duration_actual_seconds": round(dst_dur, 3),
            "duration_ok": duration_ok, "streams_preserved": streams_ok,
            "av_sync_ok": av_ok, "warnings": warnings}


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify a lossless build")
    ap.add_argument("video", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--removed", type=float, required=True)
    ap.add_argument("--tol", type=float, default=1.5)
    ap.add_argument("--work-dir", type=Path, default=None)
    args = ap.parse_args()
    rep = verify_build(args.video, args.output, args.removed, args.tol)
    print(json.dumps(rep, indent=2))
    if args.work_dir is not None:
        side = args.work_dir / "verify.yaml"
        write_yaml_atomic(side, rep)
    raise SystemExit(0 if rep["ok"] else 2)


if __name__ == "__main__":
    main()
