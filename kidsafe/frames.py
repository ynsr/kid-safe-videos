"""frames.py: deterministic frame extraction + perceptual-hash dedupe.

Frames named by timestamp: f_<seconds>.jpg. Near-duplicates dropped via
a block-hash (aHash/dHash hybrid on PIL, stdlib only).
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from PIL import Image


def extract_frames(video: Path, start: float, end: float, fps: float,
                   size: tuple[int, int], dest: Path) -> list[tuple[Path, float]]:
    dest.mkdir(parents=True, exist_ok=True)
    # Extract at exact fps between start/end, then rename by timestamp.
    tmp_pat = str(dest / "raw_%06d.jpg")
    dur = max(0.0, end - start)
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(video),
           "-t", f"{dur:.3f}", "-vf", f"fps={fps},scale={size[0]}:{size[1]}",
           "-q:v", "3", tmp_pat]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"frame extraction failed: {r.stderr[:500]}")
    raws = sorted(dest.glob("raw_*.jpg"))
    out: list[tuple[Path, float]] = []
    for i, rp in enumerate(raws):
        t = start + i / fps if fps > 0 else start
        if t > end + 1e-6:
            rp.unlink()
            continue
        name = dest / f"f_{t:08.3f}.jpg"
        rp.rename(name)
        out.append((name, round(t, 3)))
    return out


def block_hash(img: Image.Image, bits: int = 8) -> int:
    g = img.convert("L").resize((bits, bits), Image.BILINEAR)
    px = list(g.getdata())
    avg = sum(px) / len(px)
    h = 0
    for p in px:
        h = (h << 1) | (1 if p > avg else 0)
    return h


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def dedupe(frames: list[tuple[Path, float]], threshold: int = 5) -> list[tuple[Path, float]]:
    """Drop near-duplicate frames (hamming distance <= threshold vs last kept)."""
    kept: list[tuple[Path, float]] = []
    last_hash: int | None = None
    for path, t in frames:
        try:
            with Image.open(path) as im:
                h = block_hash(im)
        except OSError:
            kept.append((path, t))
            continue
        if last_hash is not None and hamming(h, last_hash) <= threshold:
            path.unlink(missing_ok=True)
            continue
        last_hash = h
        kept.append((path, t))
    return kept


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract frames for a window")
    ap.add_argument("video", type=Path)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--width", type=int, default=480)
    ap.add_argument("--height", type=int, default=270)
    ap.add_argument("--dest", type=Path, required=True)
    ap.add_argument("--no-dedupe", action="store_true")
    args = ap.parse_args()
    frames = extract_frames(args.video, args.start, args.end, args.fps,
                            (args.width, args.height), args.dest)
    if not args.no_dedupe:
        frames = dedupe(frames)
    print(f"extracted {len(frames)} frames -> {args.dest}")


if __name__ == "__main__":
    main()
