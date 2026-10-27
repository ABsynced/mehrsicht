"""Run the whole pipeline for one or both editions.

Usage (from the project folder):
    python -m pipeline.run --edition all            # live: real feeds + AI
    python -m pipeline.run --edition de --offline   # demo data, no internet, no API key
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import archive, config, factfeeds
from .analyze import analyse, build_story
from .cluster import cluster
from .factcheck import disinfo_of_the_moment
from .fetch import fetch_all
from .images import pick_image
from .llm import LLM
from .logos import fetch_all_logos
from .trending import build_topics, trending

log = logging.getLogger("mehrsicht")

MAX_STORIES = 30  # new/updated stories per run


def word_of_the_week(stories: list[dict]) -> dict | None:
    counter, sides = Counter(), {}
    for story in stories:
        for fw in story["framing_words"]:
            word = fw["word"].strip("„“\"' ")
            if word:
                counter[word] += 1
                sides.setdefault(word, Counter())[fw["side"]] += 1
    if not counter:
        return None
    word, count = counter.most_common(1)[0]
    return {"word": word, "count": count, "side": sides[word].most_common(1)[0][0]}


def party_presence(stories: list[dict], parliament: dict) -> list[dict]:
    parties = parliament["groups"] + parliament.get("other_parties", [])
    total = len(stories) or 1
    rows = []
    for p in parties:
        hits = sum(1 for s in stories if p["id"] in s["parties"])
        if hits:
            rows.append({"id": p["id"], "name": p["name"], "color": p["color"], "share": round(100 * hits / total)})
    return sorted(rows, key=lambda r: r["share"], reverse=True)


def party_labels() -> dict[str, str]:
    labels = {}
    for ed in config.EDITIONS:
        parl = config.load_parliament(ed)
        for p in parl["groups"] + parl.get("other_parties", []):
            labels[p["id"]] = p["name"]
    return labels


def run_edition(edition: str, offline: bool) -> dict:
    now = datetime.now(timezone.utc)
    llm = LLM(offline=offline)
    log.info("== Ausgabe %s · %s ==", edition.upper(), "OFFLINE-DEMO" if offline else ("KI aktiv: " + llm.describe() if llm.available else "ohne KI (kein Schlüssel gesetzt)"))
    sources = config.load_sources(edition, offline)
    topics_cfg = config.load_topics()
    topic_cfg, party_keywords = topics_cfg["topics"], topics_cfg["party_keywords"]
    parliament = config.load_parliament(edition)
    ownership = config.load_ownership()
    labels = party_labels()
    logos = fetch_all_logos(sources, offline)

    old_stories = {} if offline else archive.load(edition)
    items = fetch_all(sources, offline, edition)
    groups = cluster(items, list(topic_cfg.keys()), llm)
    # Real fact-checks from fact-checking newsrooms (see pipeline/factfeeds.py).
    checks = factfeeds.collect(edition, llm, offline, now)
    # Stories that a fact-checker has checked come first (they always get a page
    # and the AI analysis), then the biggest stories.
    for g in groups:
        g["has_check"] = factfeeds.group_has_check(g["items"], checks)
    n_checked = sum(g["has_check"] for g in groups)
    if n_checked:
        log.info("%d Geschichten passen zu einem Faktencheck und werden bevorzugt", n_checked)
    groups.sort(key=lambda g: (g["has_check"], len({i["source_id"] for i in g["items"]})), reverse=True)
    groups = groups[:MAX_STORIES]

    taken: set[str] = set()
    used_images = {s["image"].get("remote_url") for s in old_stories.values() if s.get("image")}
    updated, ai_requests, reused = [], 0, 0
    for group in groups:
        old = archive.match(group["items"], old_stories, taken)
        if old:
            taken.add(old["id"])
            articles = archive.merge_articles(old["articles"], group["items"])
            topic = old["topic"] if old["topic"] != "Sonstiges" else group["topic"]
        else:
            articles, topic = group["items"], group["topic"]
        n_sources = len({a["source_id"] for a in articles})

        if old and not archive.needs_new_analysis(old, n_sources, llm.available):
            analysis, by_ai = old["analysis"], old.get("ai", False)
            reused += 1
        else:
            analysis, by_ai = analyse(articles, llm, use_ai=ai_requests < config.AI_MAX_STORIES,
                                      known=topics_cfg.get("known_entities", []))
            ai_requests += 1
        story = build_story(articles, topic, analysis, by_ai, story_id=old["id"] if old else None,
                            party_keywords=party_keywords, party_labels=labels, topic_cfg=topic_cfg,
                            ownership=ownership)
        if old and analysis is old["analysis"]:
            story["analysed_sources"] = old.get("analysed_sources", story["source_count"])

        keep_image = old and old.get("image") and (config.DATA_DIR / old["image"]["src"]).exists()
        story["image"] = old["image"] if keep_image else pick_image(story, topic_cfg, offline, used_images)
        story["updated_at"] = now.isoformat(timespec="minutes")
        updated.append(story)

    kept = [s for sid, s in old_stories.items() if sid not in taken and archive.still_fresh(s, now)]
    stories = sorted(updated + kept, key=lambda s: s.get("last_seen") or "", reverse=True)
    for s in stories:  # (re)attach fact-checks, also to older stories from the archive
        s["factchecks"] = factfeeds.attach(s, checks) or s.get("factchecks", [])
        factfeeds.mark_highlights(s)
    factfeeds.link_to_stories(checks, stories)
    if not offline:
        archive.save(edition, stories)
    log.info("Geschichten: %d neu/aktualisiert (%d mit wiederverwendeter Analyse), %d aus dem Archiv",
             len(updated), reused, len(kept))
    if llm.calls:
        log.info("KI-Nutzung: %s", llm.usage())

    # outlet names ("Euronews", "Spiegel" …) are never topics
    outlet_names = [s["name"] for s in sources] + [s["id"] for s in sources]
    topics = build_topics(stories, list(topic_cfg.keys()), exclude=outlet_names)
    recent_cut = (now - timedelta(hours=48)).isoformat()
    recent = [s for s in stories if (s.get("last_seen") or "") >= recent_cut] or stories
    own_cats = config.load_ownership_categories()
    return {
        "edition": edition,
        "offline": offline,
        "ai": llm.calls > 0,
        "ai_model": llm.describe() if llm.calls else None,
        "generated_at": now.isoformat(timespec="minutes"),
        "sources": [{**{k: s.get(k) for k in ("id", "name", "bucket", "lean", "country")},
                     "logo": logos.get(s["id"]),
                     "ownership": ownership.get(s["id"], {}).get("category"),
                     "owner": ownership.get(s["id"], {}).get("owner")} for s in sources],
        "ownership_categories": own_cats,
        "stories": stories,
        "topics": topics,
        "trending": trending(stories, topics, now),
        "disinfo": disinfo_of_the_moment(recent) or next(({**c, "story_id": None} for c in checks if c["verdict"] == "FALSCH"), None),
        "factchecks": checks[:60],
        "word_of_week": word_of_the_week(recent),
        "party_presence": party_presence(recent, parliament),
        "parliament": parliament,
        "checks_count": len(checks),
        "press_photos": any((s.get("image") or {}).get("kind") == "press" for s in stories),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Mehrsicht-Pipeline")
    parser.add_argument("--edition", choices=["de", "eu", "all"], default="all")
    parser.add_argument("--offline", action="store_true", help="Beispieldaten statt echter Feeds und KI")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    editions = config.EDITIONS if args.edition == "all" else (args.edition,)
    for edition in editions:
        data = run_edition(edition, args.offline)
        out = config.DATA_DIR / f"edition_{edition}.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        log.info("Gespeichert: %s (%d Geschichten, %d Themen, Trends: %s)", out.relative_to(config.ROOT),
                 len(data["stories"]), len(data["topics"]), ", ".join(t["name"] for t in data["trending"][:5]) or "–")


if __name__ == "__main__":
    main()
