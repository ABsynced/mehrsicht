"""The story archive: stories stay on the site for ARCHIVE_DAYS days.

Why: so the site has more than one run's worth of news ("Mehr laden"),
a story keeps its address (bookmarks, topic pages), new articles are added
to an existing story instead of creating a duplicate, and an existing AI
analysis is reused instead of paying for it again.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from . import config

log = logging.getLogger(__name__)

ARCHIVE_DAYS = 7
MAX_ARCHIVE = 400
REANALYSE_AFTER_NEW_SOURCES = 3


def path(edition: str):
    return config.DATA_DIR / f"archive_{edition}.json"


def load(edition: str) -> dict[str, dict]:
    p = path(edition)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))["stories"]
    except (ValueError, KeyError):
        log.warning("Archiv %s beschädigt – starte neu", p.name)
        return {}


def save(edition: str, stories: list[dict]) -> None:
    data = {"saved_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "stories": {s["id"]: s for s in stories[:MAX_ARCHIVE]}}
    path(edition).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def match(group_items: list[dict], archive: dict[str, dict], taken: set[str]) -> dict | None:
    """The archived story that already contains most of these articles."""
    urls = {i["url"] for i in group_items}
    best, best_overlap = None, 0
    for sid, story in archive.items():
        if sid in taken:
            continue
        overlap = len(urls & {a["url"] for a in story["articles"]})
        if overlap > best_overlap:
            best, best_overlap = story, overlap
    if best and (best_overlap >= 2 or best_overlap / max(len(urls), 1) >= 0.4):
        return best
    return None


def merge_articles(old: list[dict], new: list[dict]) -> list[dict]:
    by_url = {a["url"]: a for a in old}
    by_url.update({a["url"]: a for a in new})
    return list(by_url.values())


def needs_new_analysis(old: dict, source_count: int, ai_possible: bool) -> bool:
    if not old.get("analysis"):
        return True
    if source_count >= old.get("analysed_sources", 0) + REANALYSE_AFTER_NEW_SOURCES:
        return True
    return ai_possible and not old.get("ai")  # upgrade a rule-based story once AI is available


def still_fresh(story: dict, now: datetime) -> bool:
    last = story.get("last_seen")
    if not last:
        return False
    return datetime.fromisoformat(last) >= now - timedelta(days=ARCHIVE_DAYS)
