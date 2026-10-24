"""scan_library.py: walk a Jellyfin library root, parse paths, write library.yaml.

Deterministic. Never guesses: unparseable names -> needs_identification.
"""
from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .util import write_yaml_atomic

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".ts"}
EXTRA_DIRS = {"extras", "trailers", "behind the scenes", "deleted scenes",
              "featurettes", "interviews", "scenes", "shorts", "other"}

MOVIE_RE = re.compile(
    r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)(?:\s*-\s*(?P<extra>.*))?$"
)
SHOW_SEASON_RE = re.compile(r"^Season\s+(?P<num>\d{1,2})$", re.IGNORECASE)
EP_RE = re.compile(
    r"^(?P<show>.+?)\s+S(?P<season>\d{1,2})E(?P<ep>\d{1,3})"
    r"(?:-?E(?P<ep2>\d{1,3}))?",
    re.IGNORECASE,
)
ID_TAG_RE = re.compile(r"\[(?P<src>imdbid|tmdbid|tvdbid)-(?P<val>[^\]]+)\]")


def parse_ids(text: str) -> dict:
    ids: dict[str, str] = {}
    for m in ID_TAG_RE.finditer(text):
        ids[m.group("src")] = m.group("val")
    return ids


def parse_nfo(nfo_path: Path) -> dict:
    out: dict = {}
    try:
        root = ET.parse(nfo_path).getroot()
    except Exception:
        return out
    def txt(tag: str):
        el = root.find(tag)
        return (el.text or "").strip() if el is not None and el.text else ""
    for k in ("title", "originaltitle", "plot", "outline", "mpaa", "certification"):
        v = txt(k)
        if v:
            out[k] = v
    try:
        if txt("year"):
            out["year"] = int(txt("year")[:4])
    except ValueError:
        pass
    try:
        if txt("runtime"):
            out["runtime"] = int(float(txt("runtime")))
    except ValueError:
        pass
    genres = [e.text.strip() for e in root.findall("genre") if e.text and e.text.strip()]
    if genres:
        out["genres"] = genres
    return out


def is_extra(path: Path, root: Path) -> bool:
    return any(p.name.lower() in EXTRA_DIRS for p in path.relative_to(root).parents)


def scan_library(library_root: Path, layout: str = "jellyfin",
                 custom_regexes: list[str] | None = None) -> list[dict]:
    items: list[dict] = []
    for f in sorted(library_root.rglob("*")):
        if not f.is_file() or f.suffix not in VIDEO_EXTS:
            continue
        if f.name.endswith("-inappropriate-parts.yml"):
            continue
        if is_extra(f, library_root):
            continue
        rec = parse_video(f, library_root, layout, custom_regexes)
        items.append(rec)
    return items


def parse_video(path: Path, library_root: Path,
               layout: str = "jellyfin",
               custom_regexes: list[str] | None = None) -> dict:
    try:
        rel = path.relative_to(library_root)
    except ValueError:
        rel = path
    ids = parse_ids(str(rel))
    nfo_data: dict = {}
    for cand in (path.with_suffix(".nfo"), path.parent / f"{path.stem}.nfo"):
        if cand.exists():
            nfo_data = parse_nfo(cand)
            break
    base: dict = {
        "file": str(rel),
        "ids": ids,
        "nfo": nfo_data,
        "files": [str(rel)],
    }
    if layout == "custom" and custom_regexes:
        for rx in custom_regexes:
            m = re.search(rx, str(rel))
            if m:
                base.update({k: v for k, v in m.groupdict().items() if v is not None})
                base["status"] = "ok"
                return base
        base.update({"type": "unknown", "status": "needs_identification",
                     "reason": "no custom regex matched"})
        return base
    parts = rel.parts
    # Movie: Movies/<Name> (<Year>)/<Name> (<Year>)[ - ...].ext
    if len(parts) >= 2 and parts[0].lower() == "movies":
        folder = parts[1]
        m = MOVIE_RE.match(path.stem.split(" - ")[0] if " - " in path.stem else path.stem)
        # multi-version suffix like "Title (1999) - 1080p"
        stem_main = path.stem
        mv = MOVIE_RE.match(stem_main)
        if mv:
            d = mv.groupdict()
            base.update({"type": "movie", "title": d["title"].strip(),
                         "year": int(d["year"]), "status": "ok"})
            if d.get("extra"):
                base["version_tag"] = d["extra"].strip()
            # multi-part: cd1/part1/dvd1
            low = path.stem.lower()
            for tag in ("cd1", "cd2", "cd3", "part1", "part2", "part3", "dvd1", "dvd2"):
                if tag in low:
                    base["multipart"] = tag
            return base
        base.update({"type": "movie", "title": folder, "status": "needs_identification",
                     "reason": f"cannot parse movie name: {path.stem!r}"})
        return base
    # Show: Shows/<Show> (<Year>)/Season NN/<Show> SNNENN[-ENN].ext
    if len(parts) >= 3 and parts[0].lower() == "shows":
        show_folder = parts[1]
        season_folder = parts[2] if len(parts) > 2 else ""
        sm = re.match(r"^(?P<show>.+?)\s*\((?P<year>\d{4})\)$", show_folder)
        title = sm.group("show").strip() if sm else show_folder
        year = int(sm.group("year")) if sm else None
        snum = None
        ssm = SHOW_SEASON_RE.match(season_folder)
        if ssm:
            snum = int(ssm.group("num"))
        em = EP_RE.match(path.stem)
        if em:
            eps = [int(em.group("ep"))]
            if em.group("ep2"):
                eps.append(int(em.group("ep2")))
            base.update({"type": "episode", "title": title, "year": year,
                         "season": int(em.group("season")) if em.group("season") else snum,
                         "episodes": eps, "status": "ok"})
            if snum == 0 or (len(parts) > 2 and "special" in season_folder.lower()):
                base["special"] = True
            return base
        base.update({"type": "episode", "title": title, "year": year,
                     "status": "needs_identification",
                     "reason": f"cannot parse episode name: {path.stem!r}"})
        return base
    base.update({"type": "unknown", "status": "needs_identification",
                 "reason": f"name does not match Jellyfin layout: {str(rel)!r}"})
    return base


def collapse_multipart(items: list[dict]) -> list[dict]:
    """Group cd1/cd2 style parts of one title into a single record with files list."""
    grouped: dict[tuple, dict] = {}
    out: list[dict] = []
    for it in items:
        if it.get("multipart"):
            key = (it.get("type"), it.get("title"), it.get("year"),
                   it.get("season"), tuple(it.get("episodes", [])))
            if key in grouped:
                grouped[key]["files"].append(it["file"])
                continue
            grouped[key] = it
            out.append(it)
        else:
            out.append(it)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan a Jellyfin library into library.yaml")
    ap.add_argument("library_root", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("work/library.yaml"))
    ap.add_argument("--layout", default="jellyfin", choices=["jellyfin", "custom"])
    ap.add_argument("--regex", action="append", default=[])
    args = ap.parse_args()
    items = collapse_multipart(scan_library(args.library_root.resolve(), args.layout, args.regex))
    write_yaml_atomic(args.out, {"items": items})
    need = sum(1 for i in items if i.get("status") == "needs_identification")
    print(f"scanned {len(items)} items, {need} need identification -> {args.out}")


if __name__ == "__main__":
    main()
