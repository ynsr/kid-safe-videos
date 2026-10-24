"""suitability_gate.py: deterministic hard-rule gate from rules.yaml + .nfo.

Returns not_recommended immediately on excluded certification/genre/keyword.
Otherwise returns a pass-through with review flag. No models involved.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .util import load_yaml, write_yaml_atomic


def gate(nfo: dict, rules: dict) -> dict:
    fv = (rules.get("family_values") or {})
    excluded_certs = set(c.upper() for c in (fv.get("excluded_certifications") or []))
    allowed = set(c.upper() for c in (fv.get("allowed_certifications") or []))
    review = set(c.upper() for c in (fv.get("review_certifications") or []))
    excluded_genres = set(g.lower() for g in (fv.get("excluded_genres") or []))
    excluded_kw = [k.lower() for k in (fv.get("excluded_keywords") or [])]

    cert = str(nfo.get("certification") or nfo.get("mpaa") or "").upper().strip()
    genres = [str(g) for g in (nfo.get("genres") or [])]
    plot = " ".join(str(nfo.get(k, "")) for k in ("plot", "outline", "title")).lower()

    if cert and cert in excluded_certs:
        return {"gate": "not_recommended", "reason": f"certification {cert} is excluded"}
    for g in genres:
        if g.lower() in excluded_genres:
            return {"gate": "not_recommended", "reason": f"genre {g} is excluded"}
    for kw in excluded_kw:
        if kw and kw in plot:
            return {"gate": "not_recommended", "reason": f"excluded keyword {kw!r} in metadata"}
    if cert and cert in allowed:
        return {"gate": "pass", "reason": f"certification {cert} allowed"}
    if cert and cert in review:
        return {"gate": "needs_research", "reason": f"certification {cert} needs research"}
    return {"gate": "needs_research", "reason": "no certification allow-list match"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply deterministic suitability gate")
    ap.add_argument("work_dir", type=Path)
    ap.add_argument("--config", type=Path, default=Path("config"))
    args = ap.parse_args()
    cfg = load_config(args.config)
    ctx_p = args.work_dir / "context.yaml"
    ctx = load_yaml(ctx_p) if ctx_p.exists() else {}
    result = gate(ctx.get("nfo", {}), cfg.rules)
    suit_p = args.work_dir / "suitability.yaml"
    existing = load_yaml(suit_p) if suit_p.exists() else {}
    existing["gate"] = result
    write_yaml_atomic(suit_p, existing)
    print(f"gate={result['gate']} reason={result['reason']}")


if __name__ == "__main__":
    main()
