"""probe.py: ffprobe duration/fps/streams + keyframe timestamps. Cached in keyframes.json."""
from __future__ import annotations

import argparse
import json
import subprocess
from fractions import Fraction
from pathlib import Path

from .util import sha256_partial, write_json_atomic, load_json


def parse_fps(value: str) -> float:
    value = value.strip()
    if "/" in value:
        n, d = value.split("/", 1)
        return float(Fraction(int(n), int(d)))
    return float(value)


def ffprobe_json(path: Path) -> dict:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {r.stderr[:500]}")
    return json.loads(r.stdout)


def probe_video(path: Path) -> dict:
    info = ffprobe_json(path)
    fmt = info.get("format", {})
    streams = info.get("streams", [])
    duration = float(fmt.get("duration", 0) or 0)
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    v = vstreams[0] if vstreams else {}
    fps = 0.0
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            fps = parse_fps(str(v.get(key, "0")))
            if fps > 0:
                break
        except (ValueError, ZeroDivisionError):
            continue
    audio_tracks = [
        {"index": s.get("index"), "codec": s.get("codec_name"),
         "channels": s.get("channels"), "language": (s.get("tags") or {}).get("language")}
        for s in streams if s.get("codec_type") == "audio"
    ]
    return {
        "duration_seconds": duration,
        "fps": fps,
        "r_frame_rate": str(v.get("r_frame_rate", "")),
        "avg_frame_rate": str(v.get("avg_frame_rate", "")),
        "streams": [
            {"index": s.get("index"), "type": s.get("codec_type"),
             "codec": s.get("codec_name"),
             "width": s.get("width"), "height": s.get("height")}
            for s in streams
        ],
        "audio_tracks": audio_tracks,
        "container": fmt.get("format_name", ""),
        "size_bytes": path.stat().st_size,
        "fingerprint": {"algo": "sha256-partial", "value": sha256_partial(path)},
    }


def extract_keyframes(path: Path) -> list[float]:
    """Keyframe (packet flag K) timestamps via ffprobe packet dump."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "packet=pts_time,flags",
           "-of", "csv=p=0", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"keyframe probe failed for {path}: {r.stderr[:500]}")
    kfs: list[float] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        try:
            t = float(parts[0])
        except ValueError:
            continue
        # K flag may appear in any trailing column (e.g. "0.0,K__" or "0.0,_,K")
        if any("K" in p for p in parts[1:]):
            kfs.append(t)
    return sorted(kfs)


def probe_and_cache(video: Path, work_dir: Path) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    probe = probe_video(video)
    write_json_atomic(work_dir / "probe.json", probe)
    kf_path = work_dir / "keyframes.json"
    if kf_path.exists():
        try:
            kfs = load_json(kf_path)
            if isinstance(kfs, dict):
                kfs = kfs.get("keyframes", [])
        except Exception:
            kfs = None
    else:
        kfs = None
    if kfs is None:
        kfs = extract_keyframes(video)
        write_json_atomic(kf_path, {"keyframes": kfs, "source": str(video)})
    probe["keyframes_file"] = str(kf_path)
    probe["keyframe_count"] = len(kfs or [])
    return probe


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe a video and cache keyframes")
    ap.add_argument("video", type=Path)
    ap.add_argument("--work-dir", type=Path, required=True)
    args = ap.parse_args()
    probe = probe_and_cache(args.video.resolve(), args.work_dir)
    print(f"duration={probe['duration_seconds']:.2f}s fps={probe['fps']:.2f} "
          f"keyframes={probe['keyframe_count']}")


if __name__ == "__main__":
    main()
