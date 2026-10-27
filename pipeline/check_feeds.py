"""Quick test: does every news feed in config/ still work?

Usage:  python -m pipeline.check_feeds
Prints one line per outlet: OK with the number of headlines, or the problem.
No AI is used and nothing is saved.
"""
from __future__ import annotations

import logging

from . import config
from .fetch import fetch_source


def main() -> None:
    logging.basicConfig(level=logging.ERROR)
    broken = 0
    for edition in config.EDITIONS:
        print(f"\n== Ausgabe {edition.upper()} ==")
        for source in config.load_sources(edition, offline=False):
            items = fetch_source(source, offline=False, edition=edition)
            if items:
                print(f"  OK      {source['id']:<14} {len(items):>3} Meldungen   z. B. „{items[0]['title'][:60]}“")
            else:
                broken += 1
                print(f"  FEHLER  {source['id']:<14} keine Meldungen – Adresse prüfen: {source['rss']}")
    import feedparser, requests
    from .factfeeds import load_checkers
    print("\n== Faktencheck-Feeds ==")
    seen = set()
    for edition in config.EDITIONS:
        for c in load_checkers(edition):
            if not c.get("rss") or c["rss"] in seen:
                continue
            seen.add(c["rss"])
            try:
                feed = feedparser.parse(requests.get(c["rss"], timeout=20, headers={"User-Agent": config.USER_AGENT}).content)
                n = len(feed.entries)
            except requests.RequestException:
                n = 0
            if n:
                print(f"  OK      {c['name']:<24} {n:>3} Artikel   z. B. „{feed.entries[0].get('title', '')[:50]}“")
            else:
                broken += 1
                print(f"  FEHLER  {c['name']:<24} keine Artikel – Adresse prüfen: {c['rss']}")
    print("  (Mit FACTCHECK_API_KEY in .env kommen zusätzlich dpa, AFP, BR24 u. a. über Google dazu.)"
          if not config.FACTCHECK_API_KEY else "  Google-Faktencheck-Schlüssel ist gesetzt.")
    print(f"\n{broken} Feed(s) mit Problemen." if broken else "\nAlle Feeds funktionieren.")


if __name__ == "__main__":
    main()
