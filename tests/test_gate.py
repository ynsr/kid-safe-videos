"""Suitability gate hard rules."""
from kidsafe.suitability_gate import gate


def rules():
    return {"family_values": {
        "allowed_certifications": ["TV-Y", "TV-Y7", "G"],
        "review_certifications": ["PG", "TV-PG"],
        "excluded_certifications": ["PG-13", "R", "TV-14", "TV-MA", "NC-17"],
        "excluded_genres": ["Horror", "Adult", "Erotic"],
        "excluded_keywords": []}}


def test_excluded_certification_blocked():
    assert gate({"certification": "PG-13"}, rules())["gate"] == "not_recommended"


def test_excluded_genre_blocked():
    assert gate({"genres": ["Animation", "Horror"]}, rules())["gate"] == "not_recommended"


def test_allowed_cert_passes():
    assert gate({"certification": "TV-Y"}, rules())["gate"] == "pass"


def test_review_cert_needs_research():
    assert gate({"certification": "PG"}, rules())["gate"] == "needs_research"


def test_no_cert_needs_research_never_pass():
    r = gate({}, rules())
    assert r["gate"] == "needs_research"
