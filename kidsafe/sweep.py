"""sweep.py: coarse whole-title safety net scan (default ON).

One frame every N seconds (config), 4x4 grids, rubric limited to the
highest-priority categories from rules.yaml. Merges hits into candidates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from . import frames as frames_mod
from . import grid as grid_mod
from . import vision as vision_mod
from .util import load_yaml, write_yaml_atomic


def category_block(cfg_rules: dict) -> tuple[str, str]:
    cats = cfg_rules.get("categories", {})
    sweep_cats = ((cfg_rules.get("pipeline", {}).get("sweep", {}) or {}).get("categories"))
    if not sweep_cats:
        sweep_cats = [k for k, v in cats.items()
                      if v.get("enabled") and v.get("priority") == 1]
    names = ", ".join(sweep_cats)
    defs = "\n".join(f"- {k}: {cats.get(k, {}).get('description', cats.get(k, {}).get('severity', ''))}"
                     for k in sweep_cats)
    return names, defs


def sweep_title(video: Path, work_dir: Path, config_dir: Path,
                prompt_dir: Path, skip: bool = False) -> dict:
    cfg = load_config(config_dir)
    probe = load_yaml(work_dir / "probe.json")
    duration = float(probe["duration_seconds"])
    sweep_cfg = (cfg.rules.get("pipeline", {}).get("sweep", {}) or {})
    interval = float(sweep_cfg.get("interval_seconds", 4))
    grid_name = str(sweep_cfg.get("grid", "4x4"))
    names, defs = category_block(cfg.rules)
    prompt_t = (prompt_dir / "grid_triage.md").read_text()

    if skip:
        rec = {"status": "skipped", "hits": []}
        write_yaml_atomic(work_dir / "sweep.yaml", rec)
        return rec

    frames_dir = work_dir / "frames" / "sweep"
    grids_dir = work_dir / "grids" / "sweep"
    # extract one frame per interval across whole title
    fps = 1.0 / interval
    extracted = frames_mod.extract_frames(video, 0.0, duration, fps, (480, 270), frames_dir)
    kept = frames_mod.dedupe(extracted)
    grids = grid_mod.build_grids(kept, grid_name, grids_dir)
    cache_dir = work_dir / "vision_cache"
    log_path = work_dir / "logs" / "vision_calls.jsonl"
    hits: list[dict] = []
    for g in grids:
        tiles = {int(k): float(v) for k, v in g["tiles"].items()}
        subs = {"categories": names, "category_definitions": defs, "context_block": ""}
        rec = vision_mod.query_grid(Path(g["image"]), tiles, prompt_t, subs,
                                    "frame_triage", config_dir, cache_dir, log_path)
        for f in rec["parsed"]["flagged"]:
            t = tiles[f["tile"]]
            hits.append({"time": t, "grid": Path(g["image"]).name,
                         "tile": f["tile"], "category": f["category"],
                         "answer": f["answer"], "reason": f["reason"]})
    # escalation for UNSURE/conflicts could go here; union votes flag all
    rec_out = {"status": "done", "interval_seconds": interval, "grid": grid_name,
               "categories": names.split(", "), "frames": len(kept),
               "grids": len(grids), "hits": sorted(hits, key=lambda h: h["time"])}
    write_yaml_atomic(work_dir / "sweep.yaml", rec_out)
    return rec_out


def main() -> None:
    ap = argparse.ArgumentParser(description="Coarse whole-title sweep")
    ap.add_argument("video", type=Path)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=Path("config"))
    ap.add_argument("--prompts", type=Path, default=Path("prompts"))
    ap.add_argument("--skip", action="store_true")
    args = ap.parse_args()
    rec = sweep_title(args.video.resolve(), args.work_dir, args.config, args.prompts, args.skip)
    print(f"sweep {rec['status']}: {len(rec.get('hits', []))} hits")


if __name__ == "__main__":
    main()
