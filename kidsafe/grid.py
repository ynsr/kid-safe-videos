"""grid.py: tile N frames into one image with burnt-in tile numbers.

Supports 2x2/3x3/4x4, consecutive grids overlap by one tile. Emits a JSON
mapping tile number -> timestamp. Timestamps come ONLY from this mapping.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GRID_SIZES = {"2x2": (2, 2), "3x3": (3, 3), "4x4": (4, 4)}


def load_font(size: int):
    for fp in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
               "/System/Library/Fonts/Helvetica.ttc",
               "/System/Library/Fonts/Menlo.ttc"):
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except OSError:
                continue
    return ImageFont.load_default()


def build_grids(frames: list[tuple[Path, float]], grid: str, dest: Path,
                overlap: int = 1) -> list[dict]:
    cols, rows = GRID_SIZES[grid]
    per = cols * rows
    step = per - overlap
    dest.mkdir(parents=True, exist_ok=True)
    grids: list[dict] = []
    idx = 0
    i = 0
    while i < len(frames):
        chunk = frames[i:i + per]
        if len(chunk) < 2 and i > 0:
            break
        thumbs: list[Image.Image] = []
        for p, _t in chunk:
            with Image.open(p) as im:
                thumbs.append(im.convert("RGB").copy())
        tw, th = thumbs[0].size
        canvas = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
        font = load_font(max(14, th // 12))
        mapping: dict[int, float] = {}
        for n, ((p, t), th_) in enumerate(zip(chunk, thumbs)):
            r, c = divmod(n, cols)
            canvas.paste(th_, (c * tw, r * th))
            d = ImageDraw.Draw(canvas)
            label = str(n)
            x0, y0 = c * tw + 6, r * th + 6
            bbox = d.textbbox((x0, y0), label, font=font)
            d.rectangle([bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 2], fill=(0, 0, 0))
            d.text((x0, y0), label, fill=(255, 220, 60), font=font)
            mapping[n] = t
        gpath = dest / f"grid_{idx:04d}.jpg"
        canvas.save(gpath, quality=90)
        meta = {"image": gpath.name, "grid": grid, "tiles": mapping}
        (dest / f"grid_{idx:04d}.json").write_text(json.dumps(meta, indent=2))
        grids.append({"image": str(gpath), "meta": str(dest / f"grid_{idx:04d}.json"),
                      "tiles": mapping})
        idx += 1
        if i + per >= len(frames):
            break
        i += step
    return grids


def main() -> None:
    ap = argparse.ArgumentParser(description="Tile frames into numbered grids")
    ap.add_argument("frames_dir", type=Path)
    ap.add_argument("--grid", default="3x3", choices=list(GRID_SIZES))
    ap.add_argument("--dest", type=Path, required=True)
    args = ap.parse_args()
    fps: list[tuple[Path, float]] = []
    for p in sorted(args.frames_dir.glob("f_*.jpg")):
        try:
            t = float(p.stem[2:])
        except ValueError:
            continue
        fps.append((p, t))
    grids = build_grids(fps, args.grid, args.dest)
    print(f"built {len(grids)} grids -> {args.dest}")


if __name__ == "__main__":
    main()
