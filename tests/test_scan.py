"""Jellyfin path parsing: movies, episodes, multi-episode, ID tags, specials."""
from pathlib import Path

from kidsafe.scan_library import parse_video


def pv(rel: str) -> dict:
    return parse_video(Path(rel), Path("/lib"))


def test_movie_basic():
    r = pv("Movies/Tarzan (1999)/Tarzan (1999).mp4")
    assert r["type"] == "movie" and r["title"] == "Tarzan" and r["year"] == 1999
    assert r["status"] == "ok"


def test_movie_multiversion_suffix():
    r = pv("Movies/Tarzan (1999)/Tarzan (1999) - 1080p.mkv")
    assert r["status"] == "ok" and r.get("version_tag") == "1080p"


def test_movie_id_tags():
    r = pv("Movies/Tarzan (1999) [imdbid-tt0120855]/Tarzan (1999).mp4")
    assert r["ids"].get("imdbid") == "tt0120855"


def test_episode_basic():
    r = pv("Shows/Bluey (2018)/Season 01/Bluey S01E02.mkv")
    assert r["type"] == "episode" and r["season"] == 1 and r["episodes"] == [2]


def test_episode_multi():
    r = pv("Shows/Bluey (2018)/Season 01/Bluey S01E02-E03.mkv")
    assert r["episodes"] == [2, 3]


def test_episode_special():
    r = pv("Shows/Bluey (2018)/Season 00/Bluey S00E01.mkv")
    assert r.get("special") is True


def test_unparseable_needs_identification():
    r = pv("Shows/Bluey (2018)/Season 01/random_file.mkv")
    assert r["status"] == "needs_identification"


def test_non_jellyfin_needs_identification():
    r = pv("stuff/clip_final_v2.mp4")
    assert r["status"] == "needs_identification"
