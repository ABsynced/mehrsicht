"""Step 1: download the RSS feeds and turn them into a flat list of items.

We only keep what RSS feeds publish openly: headline, short teaser, link and
time. Full articles are never copied (German press law protects them).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from . import config
from .textutil import clean_html, truncate

log = logging.getLogger(__name__)


def _published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


IMG_IN_HTML = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def _image(entry) -> tuple[str | None, str | None]:
    """Find the article photo that the outlet itself put into its RSS feed.

    Feeds use different tags for this (media:content, media:thumbnail,
    enclosure, or an <img> inside the text). Returns (url, credit).
    """
    candidates = []
    for media in entry.get("media_content", []) or []:
        if media.get("medium") == "image" or str(media.get("type", "")).startswith("image") or media.get("url", "").lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
            candidates.append((int(media.get("width") or 0), media.get("url")))
    for thumb in entry.get("media_thumbnail", []) or []:
        candidates.append((int(thumb.get("width") or 0), thumb.get("url")))
    for enc in entry.get("enclosures", []) or []:
        if str(enc.get("type", "")).startswith("image"):
            candidates.append((0, enc.get("href") or enc.get("url")))
    if not candidates:
        html = " ".join([entry.get("summary", "")] + [c.get("value", "") for c in entry.get("content", []) or []])
        match = IMG_IN_HTML.search(html)
        if match:
            candidates.append((0, match.group(1)))
    candidates = [(w, u) for w, u in candidates if u and u.startswith("http")]
    if not candidates:
        return None, None
    url = max(candidates, key=lambda c: c[0])[1]

    credit = None
    raw_credit = entry.get("media_credit") or entry.get("credit")
    if isinstance(raw_credit, list) and raw_credit:
        raw_credit = raw_credit[0].get("content") if isinstance(raw_credit[0], dict) else raw_credit[0]
    if isinstance(raw_credit, dict):
        raw_credit = raw_credit.get("content")
    if isinstance(raw_credit, str) and raw_credit.strip():
        credit = clean_html(raw_credit)[:80]
    return url, credit


def _parse(raw: bytes | str, source: dict) -> list[dict]:
    feed = feedparser.parse(raw)
    items = []
    for entry in feed.entries:
        title = clean_html(entry.get("title", ""))
        if not title:
            continue
        published = _published(entry)
        image_url, image_credit = _image(entry)
        items.append({
            "image_url": image_url,
            "image_credit": image_credit,
            "source_id": source["id"],
            "source_name": source["name"],
            "bucket": source["bucket"],
            "lean": source.get("lean", 0),
            "country": source.get("country", "DE"),
            "lang": source.get("lang", "de"),
            "title": title,
            "summary": truncate(clean_html(entry.get("summary", ""))),
            "url": entry.get("link", ""),
            "published": published.isoformat() if published else None,
        })
    return items


def fetch_source(source: dict, offline: bool, edition: str) -> list[dict]:
    """Return the items of one outlet. Offline mode reads a local demo file."""
    if offline:
        path = config.FIXTURES_DIR / "rss" / edition / f"{source['id']}.xml"
        if not path.exists():
            return []
        return _parse(path.read_text(encoding="utf-8"), source)
    try:
        resp = requests.get(source["rss"], timeout=20, headers={"User-Agent": config.USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Feed %s nicht erreichbar: %s", source["id"], exc)
        return []
    return _parse(resp.content, source)


def fetch_all(sources: list[dict], offline: bool, edition: str, max_age_hours: int = 36) -> list[dict]:
    items: list[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    for source in sources:
        got = fetch_source(source, offline, edition)
        if not offline:
            got = [i for i in got if not i["published"] or datetime.fromisoformat(i["published"]) >= cutoff]
        log.info("%-16s %3d Meldungen", source["id"], len(got))
        items.extend(got)
    # Give every item a stable number the AI can refer to.
    for idx, item in enumerate(items):
        item["n"] = idx
    return items
