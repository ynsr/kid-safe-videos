"""Shared deterministic utilities: atomic writes, subprocess, timecodes, fingerprints."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def check_ffmpeg() -> tuple[str, str]:
    ff = run_cmd(["ffmpeg", "-version"])
    fp = run_cmd(["ffprobe", "-version"])
    if ff.returncode != 0:
        raise RuntimeError("ffmpeg not found on PATH. Install ffmpeg >= 4.x.")
    if fp.returncode != 0:
        raise RuntimeError("ffprobe not found on PATH. Install ffmpeg >= 4.x.")
    first_ff = (ff.stdout or "").splitlines()[0] if ff.stdout else "ffmpeg"
    first_fp = (fp.stdout or "").splitlines()[0] if fp.stdout else "ffprobe"
    return first_ff, first_fp


def format_timecode(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h = total_ms // 3_600_000
    m = (total_ms % 3_600_000) // 60_000
    s = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def parse_timecode(tc: str) -> float:
    parts = tc.split(":")
    if len(parts) != 3:
        raise ValueError(f"bad timecode: {tc!r}")
    h = int(parts[0])
    m = int(parts[1])
    sec_ms = parts[2].split(".")
    s = int(sec_ms[0])
    ms = int(sec_ms[1]) if len(sec_ms) > 1 else 0
    return h * 3600 + m * 60 + s + ms / 1000.0


def sha256_partial(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    """Fingerprint: size + SHA-256 over first, middle, last 4 MiB."""
    size = path.stat().st_size
    h = hashlib.sha256()
    h.update(f"size:{size}".encode())
    if size == 0:
        return h.hexdigest()
    with open(path, "rb") as f:
        # first
        h.update(f.read(chunk))
        # middle
        if size > chunk:
            mid = max(0, size // 2 - chunk // 2)
            f.seek(mid)
            h.update(f.read(chunk))
        # last
        if size > chunk:
            f.seek(max(0, size - chunk))
            h.update(f.read(chunk))
    return h.hexdigest()


def sha256_full(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def load_yaml(path: Path):
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump_yaml(data) -> str:
    import yaml

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)


def write_yaml_atomic(path: Path, data) -> None:
    atomic_write_text(path, dump_yaml(data))


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, data) -> None:
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")
