"""proxy.py: low-res H.264/AAC preview for the UI only. Never used for final output."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def build_proxy(video: Path, dest: Path, width: int = 640,
                preset: str = "veryfast", crf: int = 28) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    cmd = ["ffmpeg", "-y", "-i", str(video),
           "-vf", f"scale={width}:-2", "-c:v", "libx264",
           "-preset", preset, "-crf", str(crf),
           "-c:a", "aac", "-b:a", "96k",
           "-movflags", "+faststart", str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"proxy build failed: {r.stderr[-800:]}")
    import os
    os.replace(tmp, dest)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a UI preview proxy")
    ap.add_argument("video", type=Path)
    ap.add_argument("--dest", type=Path, required=True)
    args = ap.parse_args()
    p = build_proxy(args.video.resolve(), args.dest)
    print(f"proxy -> {p}")


if __name__ == "__main__":
    main()
