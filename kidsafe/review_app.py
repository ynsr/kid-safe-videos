"""review_app.py: Flask review UI backend on 127.0.0.1. State in work/<id> files."""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from .cut import run_cut
from .proxy import build_proxy
from .sidecar import build_sidecar, validate_sidecar, write_sidecar
from .util import atomic_write_text, dump_yaml, format_timecode, load_json, load_yaml
from .verify import verify_build

app = Flask(__name__)
WORK_ROOT = Path("work")
CONFIG_DIR = Path("config")
PROMPTS_DIR = Path("prompts")
_lock = threading.Lock()


def wdir(id_: str) -> Path:
    p = (WORK_ROOT / id_).resolve()
    if WORK_ROOT.resolve() not in p.parents and p != WORK_ROOT.resolve():
        raise ValueError("bad id")
    return p


def read_state(id_: str) -> dict:
    wd = wdir(id_)
    cands = {}
    for name in ("candidates.yaml", "cuts.yaml"):
        p = wd / name
        if p.exists():
            cands = load_yaml(p)
    clist = cands.get("candidates", cands.get("cuts", []))
    probe = load_yaml(wd / "probe.json") if (wd / "probe.json").exists() else {}
    suit = load_yaml(wd / "suitability.yaml") if (wd / "suitability.yaml").exists() else {}
    burden = load_yaml(wd / "cut_burden.yaml") if (wd / "cut_burden.yaml").exists() else None
    return {"candidates": clist, "duration": probe.get("duration_seconds", 0),
            "suitability": ((suit.get("title_level") or {}).get("verdict")),
            "burden": burden, "warnings": burden.get("reasons", []) if burden else []}


@app.get("/")
def index():
    return send_file(Path(__file__).resolve().parent.parent / "ui" / "index.html")


@app.get("/api/state")
def api_state():
    return jsonify(read_state(request.args["id"]))


@app.get("/api/proxy")
def api_proxy():
    wd = wdir(request.args["id"])
    ctx = load_yaml(wd / "context.yaml") if (wd / "context.yaml").exists() else {}
    video = Path(ctx.get("video", ""))
    proxy = wd / "proxy" / "preview.mp4"
    if not proxy.exists() and video.exists():
        build_proxy(video, proxy)
    return jsonify({"url": "/media/proxy"})


@app.get("/media/proxy")
def media_proxy():
    wd = wdir(request.args["id"])
    return send_file(wd / "proxy" / "preview.mp4")


@app.post("/api/decide")
def api_decide():
    b = request.get_json(force=True)
    wd = wdir(request.args["id"])
    with _lock:
        cuts_p = wd / "cuts.yaml"
        if cuts_p.exists():
            data = load_yaml(cuts_p)
            key = "cuts"
        else:
            data = load_yaml(wd / "candidates.yaml")
            key = "candidates"
        for c in data.get(key, []):
            if c.get("id") == b["id"]:
                dec = b["decision"]
                c["status"] = dec
                c["decision"] = dec
                if dec == "corrected":
                    c["start_seconds"] = float(b.get("start", c.get("start", c.get("start_seconds"))))
                    c["end_seconds"] = float(b.get("end", c.get("end", c.get("end_seconds"))))
                if b.get("note") is not None:
                    c["note"] = b["note"]
                # persist cut snap info
                try:
                    kf = load_json(wd / "keyframes.json")
                    kfs = kf.get("keyframes", []) if isinstance(kf, dict) else kf
                    from .cut import snap_outward
                    s = float(c.get("start_seconds", c.get("start")))
                    e = float(c.get("end_seconds", c.get("end")))
                    ss, ee, extra, _w = snap_outward(s, e, kfs)
                    c["cut"] = {"start_seconds_snapped": ss, "end_seconds_snapped": ee,
                                "extra_removed_seconds": extra,
                                "output_join_at_seconds": None}
                except Exception:  # noqa: BLE001
                    pass
                break
        atomic_write_text(cuts_p, dump_yaml({"cuts": data.get(key, [])}))
        # regenerate sidecar on every decision
        try:
            ctx = load_yaml(wd / "context.yaml") if (wd / "context.yaml").exists() else {}
            if ctx.get("video"):
                write_sidecar(Path(ctx["video"]), wd, CONFIG_DIR)
        except Exception:  # noqa: BLE001
            pass
    return jsonify({"ok": True})


@app.get("/api/snap")
def api_snap():
    wd = wdir(request.args["id"])
    s, e = float(request.args["start"]), float(request.args["end"])
    kf = load_json(wd / "keyframes.json")
    kfs = kf.get("keyframes", []) if isinstance(kf, dict) else kf
    from .cut import snap_outward
    ss, ee, extra, warnings = snap_outward(s, e, kfs)
    return jsonify({"snapped": [ss, ee], "extra": extra, "warnings": warnings,
                    "tc": [format_timecode(ss), format_timecode(ee)]})


@app.get("/api/next")
def api_next():
    st = read_state(request.args["id"])
    for c in st["candidates"]:
        if c.get("status", c.get("decision", "pending")) == "pending":
            return jsonify({"id": c["id"]})
    return jsonify({"id": None})


@app.get("/api/join")
def api_join():
    """3s before start + 3s after end back to back (re-encoded preview only)."""
    wd = wdir(request.args["id"])
    ctx = load_yaml(wd / "context.yaml")
    video = Path(ctx["video"])
    s, e = float(request.args["start"]), float(request.args["end"])
    probe = load_yaml(wd / "probe.json")
    dur = float(probe["duration_seconds"])
    a0, a1 = max(0.0, s - 3), s
    b0, b1 = e, min(dur, e + 3)
    out = wd / "proxy" / f"join_{s:.1f}_{e:.1f}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    lst = wd / "proxy" / "join_list.txt"
    cmd = (f"ffmpeg -y -ss {a0:.3f} -i {video} -t {(a1-a0):.3f} "
           f"-ss {b0:.3f} -i {video} -t {(b1-b0):.3f} "
           f"-filter_complex '[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1' "
           f"-c:v libx264 -preset veryfast -crf 28 -c:a aac {out}")
    import shlex
    r = subprocess.run(shlex.split(cmd), capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return jsonify({"error": r.stderr[-500:]}), 500
    return jsonify({"url": f"/media/join_{s:.1f}_{e:.1f}"})


@app.post("/api/export")
def api_export():
    wd = wdir(request.args["id"])
    ctx = load_yaml(wd / "context.yaml")
    p = write_sidecar(Path(ctx["video"]), wd, CONFIG_DIR)
    return jsonify({"path": str(p)})


@app.post("/api/build")
def api_build():
    wd = wdir(request.args["id"])
    ctx = load_yaml(wd / "context.yaml")
    video = Path(ctx["video"])
    probe = load_yaml(wd / "probe.json")
    kf = load_json(wd / "keyframes.json")
    kfs = kf.get("keyframes", []) if isinstance(kf, dict) else kf
    cuts_p = wd / "cuts.yaml"
    if not cuts_p.exists():
        # promote candidates to cuts
        cands = load_yaml(wd / "candidates.yaml").get("candidates", [])
        atomic_write_text(cuts_p, dump_yaml({"cuts": [
            {**c, "start_seconds": c.get("start", 0), "end_seconds": c.get("end", 0),
             "decision": c.get("status", "pending")} for c in cands]}))
    out_root = None
    try:
        from .config import load_config
        out_root = (load_config(CONFIG_DIR).rules.get("library", {}) or {}).get("output_root")
    except Exception:  # noqa: BLE001
        pass
    out = Path(out_root or (wd / "output")) / video.name
    rep = run_cut(video, cuts_p, kfs, float(probe["duration_seconds"]), out)
    removed = sum(c["snapped"][1] - c["snapped"][0] for c in rep["snapped_cuts"])
    ver = verify_build(video, out, removed)
    atomic_write_text(wd / "verify.yaml", dump_yaml(ver))
    write_sidecar(video, wd, CONFIG_DIR)
    return jsonify({"output": str(out), "verify": ver, "warnings": rep["warnings"]})


def serve(work_root: str = "work", config: str = "config", port: int = 8808):
    global WORK_ROOT, CONFIG_DIR
    WORK_ROOT = Path(work_root)
    CONFIG_DIR = Path(config)
    app.run(host="127.0.0.1", port=port, debug=False)
