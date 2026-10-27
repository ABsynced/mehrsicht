"""Step 5: attach published fact-checks to stories.

Mehrsicht never decides on its own that something is false. Verdicts come
from professional fact-checkers that publish in the ClaimReview format
(searched through the free Google Fact Check Tools API). The AI only
suggests WHICH claims to look up.

Offline mode uses clearly labelled example fact-checks from
fixtures/factchecks_demo.json.
"""
from __future__ import annotations

import logging

import requests

from . import config
from .textutil import jaccard, split_sentences, tokens

log = logging.getLogger(__name__)

API = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

VERDICTS = [
    ("FALSCH", "false", ("falsch", "false", "fake", "unwahr", "frei erfunden", "pants on fire", "faux")),
    ("IRREFÜHREND", "misleading", ("irreführend", "misleading", "verzerrt", "trompeur")),
    ("KONTEXT FEHLT", "context", ("kontext", "context", "teilweise", "halb", "unbelegt", "missing")),
    ("STIMMT", "true", ("richtig", "stimmt", "true", "korrekt", "wahr", "vrai")),
]


def classify(rating: str) -> tuple[str, str]:
    low = (rating or "").lower()
    for label, css, words in VERDICTS:
        if any(w in low for w in words):
            return label, css
    return "UNBELEGT", "context"


def search_api(query: str, language: str) -> list[dict]:
    params = {"query": query, "languageCode": language, "pageSize": 5, "key": config.FACTCHECK_API_KEY}
    try:
        resp = requests.get(API, params=params, timeout=20)
        resp.raise_for_status()
        claims = resp.json().get("claims", [])
    except (requests.RequestException, ValueError) as exc:
        log.warning("Faktencheck-Suche fehlgeschlagen: %s", exc)
        return []
    results = []
    for claim in claims:
        for review in claim.get("claimReview", [])[:1]:
            label, css = classify(review.get("textualRating", ""))
            results.append({
                "claim": claim.get("text", ""),
                "verdict": label,
                "verdict_class": css,
                "rating_text": review.get("textualRating", ""),
                "explanation": review.get("title", ""),
                "publisher": review.get("publisher", {}).get("name", ""),
                "url": review.get("url", ""),
                "date": review.get("reviewDate"),
                "example": False,
            })
    return results


def load_demo() -> list[dict]:
    path = config.FIXTURES_DIR / "factchecks_demo.json"
    return config.load_json(path)["factchecks"] if path.exists() else []


def find_for_story(story: dict, offline: bool, language: str = "de") -> list[dict]:
    story_words = tokens(story["title"] + " " + " ".join(a["title"] + " " + a["summary"] for a in story["articles"]))
    if offline:
        found = []
        for fc in load_demo():
            if jaccard(tokens(" ".join(fc["match"])), story_words) > 0 and set(w.lower() for w in fc["match"]) <= story_words:
                label, css = classify(fc["rating"])
                found.append({**{k: fc[k] for k in ("claim", "explanation", "publisher", "url")},
                              "verdict": label, "verdict_class": css, "rating_text": fc["rating"],
                              "date": None, "example": True})
        return found
    if not config.FACTCHECK_API_KEY:
        return []
    found, seen = [], set()
    for query in story.get("claims", []) or [story["title"]]:
        for fc in search_api(query, language):
            # Only keep fact-checks that are really about this story.
            if fc["url"] in seen or jaccard(tokens(fc["claim"]), story_words) < 0.08:
                continue
            seen.add(fc["url"])
            found.append(fc)
    return found[:3]


def mark_highlights(story: dict) -> None:
    """Find the sentence in each teaser that repeats a checked claim.

    The website then underlines that sentence; hovering shows the fact-check.
    We can only do this for the short teasers we are allowed to show.
    """
    for article in story["articles"]:
        article["highlights"] = []
        for sentence in split_sentences(article["summary"]):
            for idx, fc in enumerate(story.get("factchecks", [])):
                if fc["verdict"] == "STIMMT":
                    continue
                if jaccard(tokens(sentence), tokens(fc["claim"])) >= 0.35:
                    article["highlights"].append({"text": sentence, "fc": idx})
                    break


def disinfo_of_the_moment(stories: list[dict]) -> dict | None:
    """The false claim attached to the most widely covered story."""
    candidates = []
    for story in stories:
        for fc in story.get("factchecks", []):
            if fc["verdict"] in ("FALSCH", "IRREFÜHREND"):
                candidates.append((fc["verdict"] == "FALSCH", story["source_count"], fc, story))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    _, _, fc, story = candidates[0]
    return {**fc, "story_id": story["id"], "story_title": story["title"]}
