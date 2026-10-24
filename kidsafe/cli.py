"""kidsafe CLI: single entry point for the whole pipeline."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import __version__
from .util import check_ffmpeg, load_yaml, write_yaml_atomic


def work_id_for(video: Path) -> str:
    h = hashlib.sha1(str(video.resolve()).encode()).hexdigest()[:12]
    return f"{video.stem}-{h}"


def cmd_scan(a):
    from .scan_library import collapse_multipart, scan_library
    items = collapse_multipart(scan_library(a.library_root.resolve()))
    out = a.out or Path("work/library.yaml")
    write_yaml_atomic(out, {"items": items})
    need = sum(1 for i in items if i.get("status") == "needs_identification")
    print(f"scanned {len(items)} items, {need} need identification -> {out}")


def cmd_init(a):
    from .config import load_config
    from .probe import probe_and_cache
    check_ffmpeg()
    video = a.video.resolve()
    wid = work_id_for(video)
    wd = Path("work") / wid
    probe = probe_and_cache(video, wd)
    # context.yaml skeleton
    ctx_p = wd / "context.yaml"
    if not ctx_p.exists():
        write_yaml_atomic(ctx_p, {"video": str(video), "title": video.stem,
                                  "year": None, "ids": {}, "nfo": {},
                                  "characters": [], "notes": "", "landmarks": []})
    print(f"init {wid}: duration={probe['duration_seconds']:.2f}s "
          f"keyframes={probe['keyframe_count']}")
    print(f"work dir: {wd}")
    return wid


def cmd_suitability(a):
    from .config import load_config
    from .suitability_gate import gate
    wd = Path("work") / a.id
    cfg = load_config(a.config)
    ctx = load_yaml(wd / "context.yaml") if (wd / "context.yaml").exists() else {}
    result = gate(ctx.get("nfo", {}), cfg.rules)
    suit_p = wd / "suitability.yaml"
    existing = load_yaml(suit_p) if suit_p.exists() else {}
    existing["gate"] = result
    write_yaml_atomic(suit_p, existing)
    print(f"gate={result['gate']} reason={result['reason']}")
    print("Agent: research suitability with prompts/suitability_research.md, then run validate-suitability.")


def _validate_cmd(a, fn, name):
    data = load_yaml(a.path)
    fn_args = [data] if name != "cuts" else [data, a.duration if hasattr(a, "duration") else None]
    errs = fn(*fn_args) if name != "cuts" or getattr(a, "duration", None) is not None else fn(data)
    if errs:
        print("\n".join(f"ERROR: {e}" for e in errs))
        raise SystemExit(1)
    print("OK")


def cmd_run(a):
    """All steps up to review (probe done in init; research is agent work)."""
    from .align import build_windows
    from .config import load_config
    wd = Path("work") / a.id
    cfg = load_config(a.config)
    probe = load_yaml(wd / "probe.json")
    research = load_yaml(wd / "research.yaml")
    ctx = load_yaml(wd / "context.yaml") if (wd / "context.yaml").exists() else {}
    windows, scale, warn = build_windows(research, float(probe["duration_seconds"]),
                                         cfg.rules.get("pipeline", {}), ctx.get("landmarks", []))
    write_yaml_atomic(wd / "windows.yaml", {"scale": scale, "warning": warn, "windows": windows})
    print(f"aligned scale={scale:.4f} windows={len(windows)}")
    print("Next: localise (agent-assisted vision) -> sweep -> merge -> review.")


def cmd_sweep(a):
    from .sweep import sweep_title
    wd = Path("work") / a.id
    ctx = load_yaml(wd / "context.yaml")
    rec = sweep_title(Path(ctx["video"]), wd, a.config, Path("prompts"), skip=a.skip)
    print(f"sweep {rec['status']}: {len(rec.get('hits', []))} hits")


def cmd_merge(a):
    from .merge import build_candidates
    out = build_candidates(Path("work") / a.id, a.config)
    print(f"merged {len(out['candidates'])} candidates")


def cmd_review(a):
    from .review_app import serve
    serve(port=a.port)


def cmd_cut(a):
    from .cut import run_cut
    from .util import load_json
    if a.manual:
        # kidsafe cut --manual cuts.yaml <video>
        cuts = Path(a.manual)
        video = a.video.resolve()
        wid = work_id_for(video)
        wd = Path("work") / wid
        from .probe import probe_and_cache
        probe = probe_and_cache(video, wd)
        kf = load_json(wd / "keyframes.json")
        kfs = kf.get("keyframes", []) if isinstance(kf, dict) else kf
        rep = run_cut(video, cuts, kfs, float(probe["duration_seconds"]),
                      a.out.resolve() if a.out else Path(f"{video.stem}.cut{video.suffix}"))
        print(f"wrote {rep['output']}")
        return
    wd = Path("work") / a.id
    ctx = load_yaml(wd / "context.yaml")
    video = Path(ctx["video"])
    probe = load_yaml(wd / "probe.json")
    kf = load_json(wd / "keyframes.json")
    kfs = kf.get("keyframes", []) if isinstance(kf, dict) else kf
    out = a.out or Path(f"{video.stem}.cut{video.suffix}")
    rep = run_cut(video, wd / "cuts.yaml", kfs, float(probe["duration_seconds"]), out)
    print(f"wrote {rep['output']} warnings={rep['warnings']}")


def cmd_verify(a):
    from .util import load_json
    from .verify import verify_build
    wd = Path("work") / a.id
    ctx = load_yaml(wd / "context.yaml")
    probe = load_yaml(wd / "probe.json")
    cuts = load_yaml(wd / "cuts.yaml")
    removed = sum(c["end_seconds"] - c["start_seconds"]
                  for c in cuts.get("cuts", [])
                  if c.get("decision") in ("accepted", "corrected"))
    rep = verify_build(Path(ctx["video"]), a.output, removed, a.tol)
    print(json.dumps(rep, indent=2))
    write_yaml_atomic(wd / "verify.yaml", rep)
    if not rep["ok"]:
        raise SystemExit(2)


def cmd_sidecar(a):
    from .sidecar import write_sidecar
    wd = Path("work") / a.id
    ctx = load_yaml(wd / "context.yaml")
    p = write_sidecar(Path(ctx["video"]), wd, a.config, a.out)
    print(f"sidecar -> {p}")


def cmd_import(a):
    """Preload a sidecar: accepted/corrected -> cuts, rejected stay rejected."""
    from .sidecar import check_stale
    video = a.video.resolve()
    side = video.parent / (video.stem + "-inappropriate-parts.yml")
    if not side.exists() and a.sidecar:
        side = Path(a.sidecar)
    data = load_yaml(side)
    stale, reason = check_stale(video, data, full_hash=a.full_hash)
    if stale and not a.force:
        print(f"STALE sidecar: {reason}. Re-run analysis or pass --force.")
        raise SystemExit(3)
    if stale:
        print(f"WARNING: stale sidecar ({reason}), proceeding with --force")
    wid = work_id_for(video)
    wd = Path("work") / wid
    wd.mkdir(parents=True, exist_ok=True)
    from .probe import probe_and_cache
    probe_and_cache(video, wd)
    cuts = []
    for p in data.get("parts", []):
        dec = p.get("decision", "rejected")
        cuts.append({"id": p["id"], "start_seconds": p["start_seconds"],
                     "end_seconds": p["end_seconds"], "type": p.get("type"),
                     "decision": dec, "description": p.get("description"),
                     "cut": p.get("cut"), "note": p.get("note")})
    write_yaml_atomic(wd / "cuts.yaml", {"cuts": cuts,
                                         "imported_from": str(side)})
    write_yaml_atomic(wd / "context.yaml", {"video": str(video),
                                            "title": (data.get("source") or {}).get("title", video.stem)})
    print(f"imported {len(cuts)} parts -> {wd}/cuts.yaml (rejected stay rejected)")


def cmd_status(a):
    from .sidecar import sidecar_name
    root = a.library_root.resolve()
    present, missing = 0, []
    for ext in (".mp4", ".mkv", ".avi", ".mov", ".m4v"):
        for v in root.rglob(f"*{ext}"):
            if (v.parent / sidecar_name(v)).exists():
                present += 1
            else:
                missing.append(str(v))
    print(f"sidecars present: {present}, missing: {len(missing)}")
    for m in missing[:50]:
        print(f"  MISSING {m}")


def cmd_calibrate(a):
    """Precision/recall per model/role on a labelled samples dir."""
    d = Path(a.samples)
    n_total = n_flag = 0
    for f in sorted(d.glob("*.json")):
        rec = json.loads(f.read_text())
        truth = set(rec.get("flagged_tiles", []))
        pred = set(rec.get("predicted_tiles", []))
        n_total += 1
        n_flag += len(truth & pred)
    print(f"samples={n_total} recalled_tiles={n_flag}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kidsafe", description=__doc__)
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan"); p.add_argument("library_root", type=Path)
    p.add_argument("-o", "--out", type=Path, default=None); p.set_defaults(f=cmd_scan)

    p = sub.add_parser("init"); p.add_argument("video", type=Path); p.set_defaults(f=cmd_init)

    p = sub.add_parser("suitability"); p.add_argument("id")
    p.add_argument("--config", type=Path, default=Path("config")); p.set_defaults(f=cmd_suitability)

    p = sub.add_parser("validate-research"); p.add_argument("path", type=Path)
    p.set_defaults(f=lambda a: _validate_cmd(a, __import__("kidsafe.validators", fromlist=["x"]).validate_research, "research"))

    p = sub.add_parser("validate-suitability"); p.add_argument("path", type=Path)
    p.set_defaults(f=lambda a: _validate_cmd(a, __import__("kidsafe.validators", fromlist=["x"]).validate_suitability, "suitability"))

    p = sub.add_parser("align"); p.add_argument("id")
    p.add_argument("--config", type=Path, default=Path("config"))
    def _align(a):
        from .align import build_windows
        from .config import load_config
        wd = Path("work") / a.id
        cfg = load_config(a.config)
        probe = load_yaml(wd / "probe.json")
        research = load_yaml(wd / "research.yaml")
        ctx = load_yaml(wd / "context.yaml") if (wd / "context.yaml").exists() else {}
        windows, scale, warn = build_windows(research, float(probe["duration_seconds"]),
                                             cfg.rules.get("pipeline", {}), ctx.get("landmarks", []))
        write_yaml_atomic(wd / "windows.yaml", {"scale": scale, "warning": warn, "windows": windows})
        print(f"scale={scale:.4f} windows={len(windows)}" + (f" WARNING: {warn}" if warn else ""))
    p.set_defaults(f=_align)

    p = sub.add_parser("localise"); p.add_argument("id")
    p.add_argument("--config", type=Path, default=Path("config"))
    def _localise(a):
        from .localise import localise_title
        wd = Path("work") / a.id
        ctx = load_yaml(wd / "context.yaml")
        video = Path(ctx["video"])
        rec = localise_title(video, wd, a.config, Path("prompts"))
        print(f"localise windows={rec['windows']} hits={len(rec['hits'])} -> {wd}/localise.yaml")
    p.set_defaults(f=_localise)

    p = sub.add_parser("sweep"); p.add_argument("id")
    p.add_argument("--config", type=Path, default=Path("config"))
    p.add_argument("--skip", action="store_true"); p.set_defaults(f=cmd_sweep)

    p = sub.add_parser("merge"); p.add_argument("id")
    p.add_argument("--config", type=Path, default=Path("config")); p.set_defaults(f=cmd_merge)

    p = sub.add_parser("review"); p.add_argument("id", nargs="?", default=None)
    p.add_argument("--port", type=int, default=8808); p.set_defaults(f=cmd_review)

    p = sub.add_parser("cut"); p.add_argument("id", nargs="?", default=None)
    p.add_argument("--manual", type=Path, default=None); p.add_argument("video", nargs="?", type=Path, default=None)
    p.add_argument("--out", "-o", type=Path, default=None); p.set_defaults(f=cmd_cut)

    p = sub.add_parser("verify"); p.add_argument("id"); p.add_argument("output", type=Path)
    p.add_argument("--tol", type=float, default=1.5); p.set_defaults(f=cmd_verify)

    p = sub.add_parser("sidecar"); p.add_argument("id")
    p.add_argument("--config", type=Path, default=Path("config"))
    p.add_argument("--out", type=Path, default=None); p.set_defaults(f=cmd_sidecar)

    p = sub.add_parser("import-sidecar"); p.add_argument("video", type=Path)
    p.add_argument("--sidecar", type=Path, default=None); p.add_argument("--force", action="store_true")
    p.add_argument("--full-hash", action="store_true"); p.set_defaults(f=cmd_import)
    p = sub.add_parser("calibrate"); p.add_argument("samples")
    p.set_defaults(f=cmd_calibrate)

    p = sub.add_parser("run"); p.add_argument("video", nargs="?", type=Path, default=None)
    p.add_argument("id", nargs="?", default=None)
    p.add_argument("--config", type=Path, default=Path("config")); p.set_defaults(f=cmd_run)

    return ap


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    # `run` accepts either a video path or an id; normalise into .id
    if args.cmd == "run" and getattr(args, "id", None) is None and getattr(args, "video", None):
        args.id = work_id_for(args.video.resolve())
        # ensure init happened
        wd = Path("work") / args.id
        if not (wd / "probe.json").exists():
            cmd_init(argparse.Namespace(video=args.video))
    elif args.cmd == "run" and getattr(args, "id", None) is None:
        sys.exit("run needs a video path or an id")
    args.f(args)


if __name__ == "__main__":
    main()
