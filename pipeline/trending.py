"""Topic pages and the 'Trending' bar.

Every story carries entities (people, countries, places, organisations,
concrete plans) named by the AI. A topic page exists for every entity
that appears in at least two stories, and for every category (Rente, Klima …).

Trending score of an entity = sum over its recent stories of
    number of outlets × e^(−age in hours / 24)
so a topic covered by many outlets in the last hours ranks highest,
and yesterday's news slowly fades out.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime

from .textutil import slugify

TRENDING_COUNT = 12
WINDOW_HOURS = 72


def _age_hours(story: dict, now: datetime) -> float:
    last = story.get("last_seen")
    if not last:
        return WINDOW_HOURS
    return max((now - datetime.fromisoformat(last)).total_seconds() / 3600, 0)


def _canonical(names: list[str]) -> dict[str, str]:
    """Merge short and long forms of a name: "Trump" -> "Donald Trump",
    "Merz" -> "Friedrich Merz". A one-word name is merged into the longer
    name ending with it, if there is exactly one such longer name."""
    names = sorted(set(names), key=len)
    mapping = {}
    for n in names:
        if " " in n:
            continue
        longer = {m for m in names if m != n and (m.endswith(" " + n) or m.startswith(n + " "))
                  and len(m.split()) == 2 and m[0].isupper()}
        if len(longer) == 1:
            mapping[n] = longer.pop()
    return mapping


def build_topics(stories: list[dict], categories: list[str], exclude: list[str] | None = None) -> dict[str, dict]:
    blocked = {slugify(x) for x in (exclude or []) if x}
    alias = _canonical([e for s in stories for e in s.get("entities", []) if isinstance(e, str)])
    spellings: dict[str, Counter] = defaultdict(Counter)
    members: dict[str, list[str]] = defaultdict(list)
    kind: dict[str, str] = {}
    for cat in categories:
        slug = slugify(cat)
        spellings[slug][cat] += 100  # category spelling always wins
        kind[slug] = "category"
    for s in stories:
        slugs = set()
        cat_slug = slugify(s["topic"])
        slugs.add(cat_slug)
        for name in s.get("entities", []):
            name = alias.get(name, name)
            slug = slugify(name)
            if slug in blocked:
                continue
            if slug and slug not in slugs:
                spellings[slug][name] += 1
                kind.setdefault(slug, "entity")
                slugs.add(slug)
        for slug in slugs:
            members[slug].append(s["id"])
        s["topic_slugs"] = sorted(slugs - {cat_slug})
        s["category_slug"] = cat_slug
    by_id = {s["id"]: s for s in stories}
    topics = {}
    for slug, ids in members.items():
        if kind.get(slug) == "entity" and len(ids) < 2:
            continue
        ids.sort(key=lambda i: by_id[i].get("last_seen") or "", reverse=True)
        image = next((by_id[i]["image"]["src"] for i in ids if by_id[i].get("image")), None)
        topics[slug] = {"slug": slug, "name": spellings[slug].most_common(1)[0][0], "kind": kind[slug],
                        "story_ids": ids, "image": image}
    # Only link to topics that really get a page.
    for s in stories:
        s["topic_slugs"] = [t for t in s["topic_slugs"] if t in topics]
    return topics


def trending(stories: list[dict], topics: dict[str, dict], now: datetime) -> list[dict]:
    by_id = {s["id"]: s for s in stories}
    rows = []
    for slug, t in topics.items():
        if t["kind"] != "entity":
            continue
        score = 0.0
        recent = 0
        for sid in t["story_ids"]:
            s = by_id[sid]
            age = _age_hours(s, now)
            if age <= WINDOW_HOURS:
                score += s["source_count"] * math.exp(-age / 24)
                recent += 1
        if recent:
            rows.append({"slug": slug, "name": t["name"], "score": round(score, 2), "count": len(t["story_ids"]), "image": t["image"]})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:TRENDING_COUNT]


def related_topics(topics: dict[str, dict], slug: str, limit: int = 8) -> list[str]:
    """Topics that often appear in the same stories."""
    mine = set(topics[slug]["story_ids"])
    scores = Counter()
    for other, t in topics.items():
        if other != slug:
            shared = len(mine & set(t["story_ids"]))
            if shared:
                scores[other] = shared
    return [s for s, _ in scores.most_common(limit)]
