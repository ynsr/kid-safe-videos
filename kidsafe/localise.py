"""localise.py: localise research items to timestamps via image-grid vision.

Stage 1 (triage): extract frames across each research window from
windows.yaml, tile into overlapping grids, ask the `frame_triage` role
which tiles show the described moment.
Stage 2 (refine): ask the `grid_refine` role on grids with hits for
first/last tile, widening on UNSURE.

Models only ADD flags: empty/failed output = UNSURE over the window
(recall over precision). Timestamps come ONLY from grid tile->time
maps, never from model text. Writes localise.yaml for merge.py.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import frames as frames_mod
from . import grid as grid_mod
from . import vision as vision_mod
from .config import load_config
from .util import load_yaml, write_yaml_atomic


def context_block(work_dir: Path) -> str:
    p = work_dir / "context.yaml"
    if not p.exists():
        return ""
    try:
        ctx = load_yaml(p) or {}
    except (OSError, ValueError):
        return ""
    lines = []
    for k in ("title", "year", "certification", "notes"):
        v = ctx.get(k)
        if v:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def category_defs(cfg_rules: dict) -> str:
    cats = cfg_rules.get("categories", {})
    return "\n".join(
        f"- {k}: {v.get('description', v.get('severity', ''))}"
        for k, v in cats.items() if v.get("enabled"))


def triage_to_hits(parsed: dict, tile_times: dict[int, float]) -> list[int]:
    return [f["tile"] for f in parsed.get("flagged", [])
            if f.get("tile") in tile_times]


def localise_window(video: Path, window: dict, cfg, prompt_dir: Path,
                    work_dir: Path, grid_name: str = "3x3") -> dict:
    triage_t = (prompt_dir / "grid_triage.md").read_text()
    refine_t = (prompt_dir / "grid_refine.md").read_text()
    cfg_rules = cfg.rules
    names = ", ".join(k for k, v in cfg_rules.get("categories", {}).items()
                      if v.get("enabled"))
    subs_base = {"categories": names,
                 "category_definitions": category_defs(cfg_rules),
                 "context_block": context_block(work_dir)}
    desc = window.get("description") or window.get("research_id") or ""
    frames_dir = work_dir / "frames" / f"loc_{window.get('research_id', 'x')}"
    grids_dir = work_dir / "grids" / f"loc_{window.get('research_id', 'x')}"
    # ~1 frame per 2 s of window, capped for cost
    span = max(1.0, float(window["end"]) - float(window["start"]))
    fps = min(0.5, max(0.05, 40.0 / span))
    extracted = frames_mod.extract_frames(video, float(window["start"]),
                                          float(window["end"]), fps,
                                          (480, 270), frames_dir)
    kept = frames_mod.dedupe(extracted)
    if not kept:
        return {"research_id": window.get("research_id"),
                "category": window.get("category"),
                "status": "no_frames", "hits": []}
    grids = grid_mod.build_grids(kept, grid_name, grids_dir)
    cache_dir = work_dir / "vision_cache"
    log_path = work_dir / "logs" / "vision_calls.jsonl"
    flagged_times: list[float] = []
    refine_notes: list[str] = []
    for g in grids:
        tiles = {int(k): float(v) for k, v in g["tiles"].items()}
        subs = dict(subs_base)
        subs["description"] = desc
        rec = vision_mod.query_grid(Path(g["image"]), tiles, triage_t, subs,
                                    "frame_triage", cfg.root, cache_dir, log_path)
        hits = triage_to_hits(rec["parsed"], tiles)
        if not hits:
            continue
        # refine first/last tile within this grid
        rrec = vision_mod.query_grid(Path(g["image"]), tiles, refine_t, subs,
                                     "grid_refine", cfg.root, cache_dir, log_path)
        rp = rrec.get("parsed") or {}
        first, last = rp.get("first_tile"), rp.get("last_tile")
        lo = tiles[first] if first in tiles else min(tiles[h] for h in hits)
        hi = tiles[last] if last in tiles else max(tiles[h] for h in hits)
        lo, hi = min(lo, hi), max(lo, hi)
        if rp.get("answer") == "UNSURE":
            lo, hi = min(tiles.values()), max(tiles.values())
        flagged_times += [t for _, t in kept if lo - 1e-6 <= t <= hi + 1e-6]
        refine_notes.append(f"{Path(g['image']).name}: {rec['parsed']} -> [{lo:.1f},{hi:.1f}]")
    if not flagged_times:
        return {"research_id": window.get("research_id"),
                "category": window.get("category"),
                "status": "no_hits", "hits": []}
    lo, hi = min(flagged_times), max(flagged_times)
    return {"research_id": window.get("research_id"),
            "category": window.get("category"),
            "status": "localised", "start": round(lo, 3), "end": round(hi, 3),
            "description": desc, "refine_notes": refine_notes}


def localise_title(video: Path, work_dir: Path, config_dir: Path,
                   prompt_dir: Path) -> dict:
    cfg = load_config(config_dir)
    probe = load_yaml(work_dir / "probe.json")
    _duration = float(probe["duration_seconds"])
    windows_doc = load_yaml(work_dir / "windows.yaml") or {}
    windows = windows_doc.get("windows", [])
    research = load_yaml(work_dir / "research.yaml") or {}
    by_id = {it.get("id"): it for it in research.get("items", [])}
    hits_out: list[dict] = []
    for w in windows:
        item = by_id.get(w.get("research_id"), {})
        window = dict(w)
        window["description"] = item.get("description", w.get("research_id", ""))
        rec = localise_window(video, window, cfg, prompt_dir, work_dir)
        if rec.get("status") == "localised":
            hits_out.append({"id": rec["research_id"], "start": rec["start"],
                             "end": rec["end"], "category": rec.get("category"),
                             "severity": item.get("severity", "medium"),
                             "confidence": item.get("confidence", "low"),
                             "source_url": item.get("source_url"),
                             "evidence": item.get("evidence_snippet"),
                             "description": rec.get("description", "")})
    out = {"status": "done", "windows": len(windows), "hits": hits_out}
    write_yaml_atomic(work_dir / "localise.yaml", out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Localise research items via vision grids")
    ap.add_argument("video", type=Path)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=Path("config"))
    ap.add_argument("--prompts", type=Path, default=Path("prompts"))
    args = ap.parse_args()
    rec = localise_title(args.video.resolve(), args.work_dir, args.config, args.prompts)
    print(f"localise windows={rec['windows']} hits={len(rec['hits'])}")


if __name__ == "__main__":
    main()
