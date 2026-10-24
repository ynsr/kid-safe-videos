"""merge.py: combine research-localised items + sweep hits into candidates.yaml.

Pads ranges, merges ranges closer than min_keep_gap_seconds, flags huge cuts.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .util import load_yaml, write_yaml_atomic


def merge_ranges(items: list[dict], min_keep_gap: float) -> list[dict]:
    items = sorted(items, key=lambda c: c["start"])
    merged: list[dict] = []
    for c in items:
        if merged and c["start"] - merged[-1]["end"] < min_keep_gap:
            m = merged[-1]
            m["end"] = max(m["end"], c["end"])
            m["origins"] = sorted(set(m.get("origins", []) + [c.get("origin", "")]))
            m["ids"] = m.get("ids", []) + [c.get("id")]
        else:
            c = dict(c)
            c["origins"] = [c.get("origin", "")]
            c["ids"] = [c.get("id")]
            merged.append(c)
    return merged


def build_candidates(work_dir: Path, config_dir: Path) -> dict:
    cfg = load_config(config_dir)
    pipe = cfg.rules.get("pipeline", {})
    pad = float(pipe.get("padding_seconds", 1.0))
    fv = cfg.rules.get("family_values", {}) or {}
    th = fv.get("thresholds", {}) or {}
    min_gap = float(th.get("min_keep_gap_seconds", 8))
    max_single = float(th.get("max_single_cut_seconds", 180))

    probe = load_yaml(work_dir / "probe.json")
    duration = float(probe["duration_seconds"])
    raw: list[dict] = []

    loc_p = work_dir / "localise.yaml"
    if loc_p.exists():
        for it in (load_yaml(loc_p) or {}).get("hits", []):
            s = max(0.0, float(it["start"]) - pad)
            e = min(duration, float(it["end"]) + pad)
            raw.append({"id": it.get("id", "loc"), "start": s, "end": e,
                        "category": it.get("category", "unknown"),
                        "severity": it.get("severity", "medium"),
                        "confidence": it.get("confidence", "low"),
                        "origin": "research", "source_url": it.get("source_url"),
                        "evidence": it.get("evidence"),
                        "description": it.get("description", "")})

    sw_p = work_dir / "sweep.yaml"
    if sw_p.exists():
        for h in (load_yaml(sw_p) or {}).get("hits", []):
            t = float(h["time"])
            s = max(0.0, t - pad)
            e = min(duration, t + pad)
            raw.append({"id": f"sweep@{t:.1f}", "start": s, "end": e,
                        "category": h.get("category", "unknown"),
                        "severity": "medium", "confidence": "low",
                        "origin": "sweep", "source_url": None,
                        "evidence": h.get("reason"),
                        "description": f"sweep hit at {t:.1f}s"})

    man_p = work_dir / "manual.yaml"
    if man_p.exists():
        for it in (load_yaml(man_p) or {}).get("cuts", []):
            raw.append({"id": it.get("id", "manual"), "start": float(it["start_seconds"]),
                        "end": float(it["end_seconds"]),
                        "category": it.get("type", "manual"), "severity": "medium",
                        "confidence": "med", "origin": "manual",
                        "source_url": None, "evidence": None,
                        "description": it.get("note", "manual cut")})

    merged = merge_ranges(raw, min_gap)
    cands: list[dict] = []
    for i, m in enumerate(merged, 1):
        dur = m["end"] - m["start"]
        cands.append({"id": f"c{i:03d}", "start": round(m["start"], 3),
                      "end": round(m["end"], 3), "category": m["category"],
                      "severity": m.get("severity", "medium"),
                      "confidence": m.get("confidence", "low"),
                      "origin": "+".join(o for o in m["origins"] if o),
                      "source_url": m.get("source_url"), "evidence": m.get("evidence"),
                      "description": (m.get("description") or "")[:300],
                      "status": "pending",
                      "flags": ["huge_cut"] if dur > max_single else []})
    out = {"candidates": cands}
    write_yaml_atomic(work_dir / "candidates.yaml", out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge localise+sweep hits into candidates")
    ap.add_argument("work_dir", type=Path)
    ap.add_argument("--config", type=Path, default=Path("config"))
    args = ap.parse_args()
    out = build_candidates(args.work_dir, args.config)
    print(f"merged {len(out['candidates'])} candidates")


if __name__ == "__main__":
    main()
