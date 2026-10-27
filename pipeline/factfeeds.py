"""Collect the newest real fact-checks, then attach them to our stories.

Where the fact-checks come from (config/factcheckers.yaml):
  1. With FACTCHECK_API_KEY: the free Google Fact Check Tools API, asked for
     the newest checks of each fact-checking newsroom (verdicts in ClaimReview format).
  2. Without a key: the RSS feeds of fact-checking newsrooms. For every article
     we read the ClaimReview data hidden in the page. Pages without it are
     given to the AI, which only READS the verdict the newsroom wrote.
Mehrsicht itself never decides that something is false.

Then:
  - every fact-check is compared with every story; matching ones are attached
  - news groups that match a fact-check are preferred when choosing stories
    ("deliberately pick news with misinformation")
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from . import config
from .factcheck import API, classify
from .textutil import clean_html, jaccard, split_sentences, tokens, truncate

log = logging.getLogger(__name__)

MAX_AGE_DAYS = 30
PER_SOURCE = 12
LD_JSON = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)


def load_checkers(edition: str) -> list[dict]:
    path = config.CONFIG_DIR / "factcheckers.yaml"
    return config.load_yaml(path).get(edition, []) if path.exists() else []


def _check(claim: str, rating: str, *, title: str, url: str, publisher: str, date: str | None,
           explanation: str = "") -> dict | None:
    claim = (claim or title or "").strip().strip("„“\"")
    if not claim or not rating:
        return None
    label, css = classify(rating)
    if label == "UNBELEGT" and not any(w in rating.lower() for w in ("unbelegt", "unproven", "unclear")):
        return None  # we could not read a clear verdict: better show nothing
    return {"claim": truncate(claim, 220), "verdict": label, "verdict_class": css, "rating_text": rating,
            "explanation": truncate(explanation or title, 260), "title": title, "publisher": publisher,
            "url": url, "date": date, "example": False}


# ------------------------------------------------------------ 1) Google API
def from_api(checkers: list[dict], language: str | None) -> list[dict]:
    out = []
    for c in checkers:
        if not c.get("site"):
            continue
        params = {"reviewPublisherSiteFilter": c["site"], "maxAgeDays": MAX_AGE_DAYS,
                  "pageSize": PER_SOURCE, "key": config.FACTCHECK_API_KEY}
        if language:
            params["languageCode"] = language
        try:
            resp = requests.get(API, params=params, timeout=20)
            resp.raise_for_status()
            claims = resp.json().get("claims", [])
        except (requests.RequestException, ValueError) as exc:
            log.warning("Faktencheck-API (%s): %s", c["site"], exc)
            continue
        n = 0
        for cl in claims:
            for rv in cl.get("claimReview", [])[:1]:
                fc = _check(cl.get("text", ""), rv.get("textualRating", ""), title=rv.get("title", ""),
                            url=rv.get("url", ""), publisher=rv.get("publisher", {}).get("name") or c["name"],
                            date=rv.get("reviewDate") or cl.get("claimDate"))
                if fc:
                    out.append(fc)
                    n += 1
        log.info("Faktencheck  %-24s %2d Prüfungen (API)", c["name"], n)
    return out


# ------------------------------------------------------------ 2) RSS + page
def _claimreviews(html: str) -> list[dict]:
    found = []
    for block in LD_JSON.findall(html):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                kind = node.get("@type")
                if kind == "ClaimReview" or (isinstance(kind, list) and "ClaimReview" in kind):
                    found.append(node)
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    return found


def _read_page(url: str) -> list[dict]:
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": config.USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException:
        return []
    return _claimreviews(resp.text)


def from_rss(checkers: list[dict], llm, now: datetime) -> list[dict]:
    out, unread = [], []
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    for c in checkers:
        if not c.get("rss"):
            continue
        try:
            resp = requests.get(c["rss"], timeout=20, headers={"User-Agent": config.USER_AGENT})
            feed = feedparser.parse(resp.content)
        except requests.RequestException as exc:
            log.warning("Faktencheck-Feed %s: %s", c["name"], exc)
            continue
        n = 0
        for e in feed.entries[:PER_SOURCE]:
            stamp = e.get("published_parsed") or e.get("updated_parsed")
            date = datetime(*stamp[:6], tzinfo=timezone.utc) if stamp else None
            if date and date < cutoff:
                continue
            title, link = clean_html(e.get("title", "")), e.get("link", "")
            summary = truncate(clean_html(e.get("summary", "")), 400)
            item = {"title": title, "url": link, "publisher": c["name"], "summary": summary,
                    "date": date.isoformat() if date else None}
            reviews = _read_page(link) if link else []
            fc = None
            for rv in reviews[:1]:
                rating = rv.get("reviewRating") or {}
                fc = _check(rv.get("claimReviewed", ""), rating.get("alternateName") or rating.get("name", ""),
                            title=title, url=link, publisher=c["name"], date=item["date"], explanation=summary)
            if fc:
                out.append(fc)
                n += 1
            else:
                unread.append(item)
        log.info("Faktencheck  %-24s %2d Prüfungen (Feed)", c["name"], n)
    if unread:
        out.extend(_ai_read(unread, llm))
    return out


def _ai_read(items: list[dict], llm) -> list[dict]:
    """Let the AI read the verdict the NEWSROOM wrote in its title/teaser."""
    if not llm or not llm.available:
        # Without AI: only titles that state the verdict themselves ("Falsch: …").
        out = []
        for it in items:
            m = re.match(r"^(falsch|irreführend|fake|fehlender kontext|unbelegt)\s*[:–-]\s*(.+)$", it["title"], re.I)
            if m:
                fc = _check(m.group(2), m.group(1), title=it["title"], url=it["url"],
                            publisher=it["publisher"], date=it["date"], explanation=it["summary"])
                if fc:
                    out.append(fc)
        return out
    out = []
    system = ("Du liest Artikel von Faktencheck-Redaktionen. Für jeden Artikel: Welche Behauptung wurde geprüft "
              "und welches Urteil hat die REDAKTION gefällt? Erfinde nichts. Wenn das Urteil nicht klar im Text steht, "
              "setze verdict auf \"NONE\". verdict ist eins von: FALSCH, IRREFÜHREND, KONTEXT FEHLT, STIMMT, NONE. "
              "Format: {\"items\": {\"1\": {\"claim\": \"die geprüfte Behauptung als Satz\", \"verdict\": \"...\", "
              "\"explanation\": \"ein Satz, warum\"}}}")
    for start in range(0, len(items), 15):
        chunk = items[start:start + 15]
        user = "\n\n".join(f"{n}. {it['title']}\n{it['summary']}" for n, it in enumerate(chunk, 1))
        answer = llm.json(system, user, max_tokens=2500, fast=True) or {}
        rows = answer.get("items", {}) if isinstance(answer, dict) else {}
        for n, it in enumerate(chunk, 1):
            row = rows.get(str(n)) or rows.get(n) or {}
            if not isinstance(row, dict) or str(row.get("verdict", "NONE")).upper() == "NONE":
                continue
            fc = _check(str(row.get("claim", "")), str(row.get("verdict", "")), title=it["title"], url=it["url"],
                        publisher=it["publisher"], date=it["date"], explanation=str(row.get("explanation") or it["summary"]))
            if fc:
                out.append(fc)
    return out


# ------------------------------------------------------------ public API
def collect(edition: str, llm, offline: bool, now: datetime) -> list[dict]:
    """All recent fact-checks for this edition, newest first, without duplicates."""
    if offline:
        from .factcheck import load_demo
        checks = []
        for fc in load_demo():
            label, css = classify(fc["rating"])
            checks.append({"claim": fc["claim"], "verdict": label, "verdict_class": css, "rating_text": fc["rating"],
                           "explanation": fc["explanation"], "title": fc["claim"], "publisher": fc["publisher"],
                           "url": fc["url"], "date": now.isoformat(timespec="minutes"), "example": True,
                           "match": fc.get("match", [])})
        return checks
    checkers = load_checkers(edition)
    checks = from_api(checkers, "de" if edition == "de" else None) if config.FACTCHECK_API_KEY else []
    if len(checks) < 10:
        checks += from_rss(checkers, llm, now)
    seen, unique = set(), []
    for fc in sorted(checks, key=lambda f: f.get("date") or "", reverse=True):
        key = fc["url"] or fc["claim"]
        if key not in seen:
            seen.add(key)
            unique.append(fc)
    log.info("Faktenchecks gesammelt: %d", len(unique))
    return unique


def _words(fc: dict) -> set[str]:
    if fc.get("match"):
        return {w.lower() for w in fc["match"]}
    return tokens(fc["claim"] + " " + (fc.get("title") or ""))


def score(fc: dict, text_tokens: set[str]) -> float:
    """How well a fact-check fits a story (0 = not at all)."""
    words = _words(fc)
    if not words:
        return 0.0
    if fc.get("match"):  # demo checks: all match words must appear
        return 1.0 if words <= text_tokens else 0.0
    shared = words & text_tokens
    if len(shared) < 3:
        return 0.0
    return len(shared) / len(words)


def story_tokens(story_or_items) -> set[str]:
    if isinstance(story_or_items, dict):
        items = story_or_items["articles"]
        head = story_or_items.get("title", "")
    else:
        items, head = story_or_items, ""
    return tokens(head + " " + " ".join(a["title"] + " " + (a.get("summary") or "") for a in items))


def group_has_check(items: list[dict], checks: list[dict]) -> bool:
    words = story_tokens(items)
    return any(score(fc, words) >= 0.4 for fc in checks if fc["verdict"] != "STIMMT")


def attach(story: dict, checks: list[dict], limit: int = 3) -> list[dict]:
    words = story_tokens(story)
    scored = sorted(((score(fc, words), fc) for fc in checks), key=lambda x: x[0], reverse=True)
    return [{k: v for k, v in fc.items() if k != "match"} for s, fc in scored if s >= 0.4][:limit]


def mark_highlights(story: dict) -> None:
    """Underline the teaser sentence that repeats a checked claim."""
    for article in story["articles"]:
        article["highlights"] = []
        for sentence in split_sentences(article.get("summary") or ""):
            st = tokens(sentence)
            for idx, fc in enumerate(story.get("factchecks", [])):
                if fc["verdict"] == "STIMMT":
                    continue
                claim = tokens(fc["claim"])
                if jaccard(st, claim) >= 0.3 or (len(st & claim) >= 3 and len(st & claim) / max(len(claim), 1) >= 0.5):
                    article["highlights"].append({"text": sentence, "fc": idx})
                    break


def link_to_stories(checks: list[dict], stories: list[dict]) -> None:
    """Remember for each fact-check which of our stories it belongs to."""
    by_url = {}
    for s in stories:
        for fc in s.get("factchecks", []):
            by_url.setdefault((fc["url"], fc["claim"]), (s["id"], s["title"]))
    for fc in checks:
        hit = by_url.get((fc["url"], fc["claim"]))
        fc["story_id"], fc["story_title"] = (hit if hit else (None, None))
        fc.pop("match", None)
