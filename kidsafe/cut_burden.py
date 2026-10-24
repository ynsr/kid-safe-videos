"""cut_burden.py: percent removed, counts, gaps, romance fraction vs thresholds."""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .util import load_yaml, write_yaml_atomic


def burden(candidates: list[dict], duration: float, rules: dict) -> dict:
    fv = rules.get("family_values", {}) or {}
    th = fv.get("thresholds", {}) or {}
    max_pct = float(th.get("max_percent_removed", 15))
    max_per10 = float(th.get("max_cuts_per_10min", 3))
    max_rom = float(th.get("max_romance_scene_fraction", 0.10))

    accepted = [c for c in candidates if c.get("status", "pending") != "rejected"]
    removed = sum(max(0.0, c["end"] - c["start"]) for c in accepted)
    pct = 100.0 * removed / duration if duration > 0 else 0.0
    per10 = len(accepted) / (duration / 600.0) if duration > 0 else 0.0
    rom = sum(1 for c in accepted if c.get("category") == "romantic_affection")
    rom_frac = (rom / len(accepted)) if accepted else 0.0

    verdict = "ok"
    reasons: list[str] = []
    if pct > max_pct:
        verdict = "not_recommended_after_cuts"
        reasons.append(f"{pct:.1f}% of runtime would be removed (limit {max_pct}%)")
    if per10 > max_per10:
        verdict = "not_recommended_after_cuts"
        reasons.append(f"{per10:.1f} cuts per 10 min (limit {max_per10})")
    if rom_frac > max_rom:
        verdict = "not_recommended_after_cuts"
        reasons.append(f"romance flagged in {rom_frac:.0%} of scenes (limit {max_rom:.0%})")
    if verdict == "not_recommended_after_cuts":
        reasons.append("story continuity likely broken")
    return {"percent_runtime_removed": round(pct, 2), "cut_count": len(accepted),
            "cuts_per_10_min": round(per10, 2),
            "romance_fraction": round(rom_frac, 3),
            "total_removed_seconds": round(removed, 2),
            "verdict": verdict, "reasons": reasons}


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute cut burden numbers")
    ap.add_argument("work_dir", type=Path)
    ap.add_argument("--config", type=Path, default=Path("config"))
    args = ap.parse_args()
    cfg = load_config(args.config)
    probe = load_yaml(args.work_dir / "probe.json")
    cands = (load_yaml(args.work_dir / "candidates.yaml") or {}).get("candidates", [])
    b = burden(cands, float(probe["duration_seconds"]), cfg.rules)
    write_yaml_atomic(args.work_dir / "cut_burden.yaml", b)
    print(f"verdict={b['verdict']} removed={b['percent_runtime_removed']}%")


if __name__ == "__main__":
    main()
