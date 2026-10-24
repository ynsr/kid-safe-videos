"""align.py: scale research reference times to local timeline, emit windows.yaml.

scale = local_duration / reference_runtime when both known.
Warn when they differ by more than 5% (dub/edit/PAL-speedup risk).
Optional landmark alignment from 1-3 (guide_time, local_time) pairs.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .util import load_yaml, write_yaml_atomic


def compute_scale(local_duration: float, reference_runtime: float | None) -> tuple[float, str | None]:
    if not reference_runtime:
        return 1.0, "no reference runtime; scale=1.0"
    scale = local_duration / reference_runtime
    warn = None
    if abs(scale - 1.0) > 0.05:
        warn = (f"runtime ratio {scale:.3f} differs by more than 5% "
                f"(local={local_duration:.1f}s ref={reference_runtime:.1f}s); "
                "dub/edit/PAL-speedup risk, windows widened")
    return scale, warn


def apply_landmarks(t: float, landmarks: list[dict]) -> float:
    """Piecewise-linear map through sorted (guide_time, local_time) pairs."""
    if not landmarks:
        return t
    pts = sorted(landmarks, key=lambda p: p["guide_time"])
    if t <= pts[0]["guide_time"]:
        return t + (pts[0]["local_time"] - pts[0]["guide_time"])
    for a, b in zip(pts, pts[1:]):
        if a["guide_time"] <= t <= b["guide_time"]:
            span = b["guide_time"] - a["guide_time"]
            if span <= 0:
                return a["local_time"]
            frac = (t - a["guide_time"]) / span
            return a["local_time"] + frac * (b["local_time"] - a["local_time"])
    last = pts[-1]
    return t + (last["local_time"] - last["guide_time"])


def build_windows(research: dict, local_duration: float, pipeline_cfg: dict,
                  landmarks: list[dict] | None = None) -> tuple[list[dict], float, str | None]:
    loc = pipeline_cfg.get("localise", {})
    wide_min = float(loc.get("window_minutes_wide", 8))
    explicit_min = float(loc.get("window_minutes_explicit_time", 4))
    frac = float(loc.get("window_fraction_plot_position", 0.10))
    ref = research.get("reference_runtime_seconds")
    scale, warn = compute_scale(local_duration, ref)
    if warn:
        explicit_min = wide_min  # widen explicit windows when ratio is off
    windows: list[dict] = []
    for it in research.get("items", []):
        tb = it.get("time_basis", "none")
        t = it.get("approx_time_seconds")
        if tb == "explicit" and t is not None:
            local = apply_landmarks(float(t) * scale, landmarks or [])
            half = explicit_min * 60
            start, end = max(0.0, local - half), min(local_duration, local + half)
            priority = 1
        elif tb in ("fraction_of_runtime", "plot_position") and t is not None:
            local = apply_landmarks(float(t) * scale, landmarks or [])
            half = frac * local_duration
            start, end = max(0.0, local - half), min(local_duration, local + half)
            priority = 2
        else:
            start, end, priority = 0.0, local_duration, 3  # whole movie, lowest
        windows.append({"research_id": it.get("id"), "category": it.get("category"),
                        "start": round(start, 3), "end": round(end, 3), "priority": priority})
    windows.sort(key=lambda w: (w["priority"], w["start"]))
    return windows, scale, warn


def main() -> None:
    ap = argparse.ArgumentParser(description="Build search windows from research.yaml")
    ap.add_argument("work_dir", type=Path)
    ap.add_argument("--config", type=Path, default=Path("config"))
    args = ap.parse_args()
    from .config import load_config
    cfg = load_config(args.config)
    probe = load_yaml(args.work_dir / "probe.json")
    research = load_yaml(args.work_dir / "research.yaml")
    ctx = load_yaml(args.work_dir / "context.yaml") if (args.work_dir / "context.yaml").exists() else {}
    landmarks = ctx.get("landmarks", [])
    windows, scale, warn = build_windows(research, float(probe["duration_seconds"]),
                                         cfg.rules.get("pipeline", {}), landmarks)
    write_yaml_atomic(args.work_dir / "windows.yaml",
                      {"scale": scale, "warning": warn, "windows": windows})
    print(f"scale={scale:.4f} windows={len(windows)}" + (f" WARNING: {warn}" if warn else ""))


if __name__ == "__main__":
    main()
