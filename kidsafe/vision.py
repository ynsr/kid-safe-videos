"""vision.py: call an OpenAI-compatible vision role on a numbered grid.

- Prompt = fixed rubric FIRST (provider prompt caching), then the question.
- Strict JSON parsing; unparseable/failed answers count as UNSURE (= flagged).
- Disk cache keyed by (grid sha256, prompt version, model id).
- Logs tokens + estimated cost. Union voting across roles.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path

from .config import load_config, require_vision_role
from .util import load_json, write_json_atomic, atomic_write_bytes

VERSION_RE = re.compile(r"<version>(.*?)</version>")


def prompt_version(text: str) -> str:
    m = VERSION_RE.search(text)
    return m.group(1).strip() if m else "0"


def render_prompt(template: str, subs: dict) -> str:
    out = template
    for k, v in subs.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def encode_image_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def cache_key(grid_path: Path, prompt_text: str, model: str) -> str:
    h = hashlib.sha256()
    h.update(grid_path.read_bytes())
    h.update(b"|")
    h.update(prompt_text.encode())
    h.update(b"|")
    h.update(model.encode())
    return h.hexdigest()[:32]


def parse_strict_json(text: str) -> dict | None:
    """Best-effort strict JSON extraction. Returns None when unparseable."""
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def call_role(base_url: str, model: str, api_key: str, prompt: str,
              image_b64: str, max_tokens: int, timeout: int,
              image_detail: str) -> tuple[str, dict]:
    import httpx

    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}",
                               "detail": image_detail}},
            ],
        }],
    }
    t0 = time.time()
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(base_url.rstrip("/") + "/chat/completions",
                       headers=headers, json=payload)
    except Exception as e:  # noqa: BLE001 - network failure => UNSURE
        return "", {"error": f"transport: {e}", "elapsed": round(time.time() - t0, 2)}
    try:
        data = r.json()
    except ValueError:
        return "", {"error": f"http {r.status_code}: non-JSON", "elapsed": round(time.time() - t0, 2)}
    if r.status_code >= 400:
        return "", {"error": f"http {r.status_code}: {str(data)[:300]}",
                    "elapsed": round(time.time() - t0, 2)}
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return "", {"error": "bad response envelope", "elapsed": round(time.time() - t0, 2)}
    usage = data.get("usage", {}) or {}
    usage["elapsed"] = round(time.time() - t0, 2)
    return text, usage


TRIAGE_SCHEMA_KEYS = {"flagged"}


def normalise_triage(obj: dict | None, valid_tiles: set[int]) -> dict:
    """Malformed model output -> UNSURE over all tiles (recall over precision)."""
    if obj is None or not isinstance(obj.get("flagged"), list):
        return {"flagged": [{"tile": t, "category": "unknown",
                             "answer": "UNSURE", "reason": "unparseable model output"} for t in sorted(valid_tiles)],
                "_parse": "UNSURE-fallback"}
    flagged = []
    for f in obj["flagged"]:
        if not isinstance(f, dict):
            continue
        try:
            tile = int(f.get("tile"))
        except (TypeError, ValueError):
            continue
        if tile not in valid_tiles:
            continue
        ans = str(f.get("answer", "UNSURE")).upper()
        if ans not in ("YES", "UNSURE"):
            continue
        flagged.append({"tile": tile, "category": str(f.get("category", "unknown")),
                        "answer": ans, "reason": str(f.get("reason", ""))[:200]})
    return {"flagged": flagged}


def query_grid(grid_image: Path, tiles: dict, prompt_template: str, subs: dict,
               role: str, config_dir: Path, cache_dir: Path,
               log_path: Path | None = None,
               cost_per_1k: dict | None = None) -> dict:
    cfg = load_config(config_dir)
    rc = require_vision_role(cfg, role)
    api_key = os.environ.get(rc.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"env var {rc.api_key_env} (role {role}) is not set")
    prompt = render_prompt(prompt_template, subs)
    key = cache_key(grid_image, prompt, rc.model)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{key}.json"
    if cached.exists():
        rec = load_json(cached)
        rec["_cache"] = "hit"
        return rec
    text, usage = call_role(rc.base_url, rc.model, api_key, prompt,
                            encode_image_b64(grid_image), rc.max_tokens,
                            rc.timeout, rc.image_detail)
    obj = parse_strict_json(text)
    norm = normalise_triage(obj, {int(k) for k in tiles})
    rec = {"model": rc.model, "role": role,
           "prompt_version": prompt_version(prompt_template),
           "raw": text[:4000], "parsed": norm, "usage": usage, "_cache": "miss"}
    write_json_atomic(cached, rec)
    if log_path is not None:
        line = json.dumps({"ts": time.time(), "role": role, "model": rc.model,
                           "grid": grid_image.name, "usage": usage}) + "\n"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(line)
    return rec


def union_votes(results: list[dict]) -> dict:
    """Flag a tile if ANY role answered YES or UNSURE."""
    votes: dict[int, dict] = {}
    for r in results:
        for f in r.get("parsed", {}).get("flagged", []):
            t = f["tile"]
            votes.setdefault(t, {"tile": t, "answers": [], "categories": []})
            votes[t]["answers"].append(f["answer"])
            votes[t]["categories"].append(f.get("category", "unknown"))
    return {"flagged_tiles": sorted(votes),
            "detail": votes}


def main() -> None:
    ap = argparse.ArgumentParser(description="Query a vision role on a grid image")
    ap.add_argument("grid_image", type=Path)
    ap.add_argument("--tiles-json", type=Path, required=True)
    ap.add_argument("--prompt", type=Path, required=True)
    ap.add_argument("--role", default="frame_triage")
    ap.add_argument("--config", type=Path, default=Path("config"))
    ap.add_argument("--cache-dir", type=Path, default=Path("work/vision_cache"))
    args = ap.parse_args()
    tiles = {int(k): float(v) for k, v in load_json(args.tiles_json)["tiles"].items()}
    rec = query_grid(args.grid_image, tiles, args.prompt.read_text(),
                     {}, args.role, args.config, args.cache_dir)
    print(json.dumps(rec["parsed"], indent=2))


if __name__ == "__main__":
    main()
