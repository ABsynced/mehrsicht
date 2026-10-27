"""Take screenshots of the finished website (for the README on GitHub).

Usage:  python -m site_builder.screenshots
Runs after site_builder.build. Saves JPGs to site/screenshots/, so they are
published together with the website and the README always shows today's news.
"""
from __future__ import annotations

import asyncio
import json

from PIL import Image

from pipeline import config
from site_builder.build import SITE

OUT = SITE / "screenshots"


def pick_story() -> str | None:
    """The best story to show: many sources, with a photo and a fact-check if possible."""
    path = config.DATA_DIR / "edition_de.json"
    if not path.exists():
        return None
    stories = json.loads(path.read_text(encoding="utf-8"))["stories"]
    stories = [s for s in stories if (SITE / "geschichte" / f"{s['id']}.html").exists()]
    if not stories:
        return None
    best = max(stories, key=lambda s: (bool(s.get("image")), s["source_count"] >= 4 and bool(s.get("factchecks")),
                                       s["source_count"]))
    return f"geschichte/{best['id']}.html"


def pick_topic() -> str | None:
    path = config.DATA_DIR / "edition_de.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    # trending topics first, otherwise the topic with the most stories
    ranked = (data.get("trending") or []) + sorted((data.get("topics") or {}).values(),
                                                   key=lambda t: len(t.get("story_ids", [])), reverse=True)
    for t in ranked:
        if (SITE / "thema" / f"{t['slug']}.html").exists():
            return f"thema/{t['slug']}.html"
    return None


async def _shoot() -> list[str]:
    from playwright.async_api import async_playwright

    story, topic = pick_story(), pick_topic()
    jobs = [  # (file name, page, width, height, scroll to, hover)
        ("home-desktop", "index.html", 1440, 900, 0, None),
        ("home-news-desktop", "index.html", 1440, 900, "#nachrichten", None),
        ("factchecks", "faktenchecks.html", 1440, 900, 0, None),
        ("home-mobile", "index.html", 390, 844, 0, None),
    ]
    if story:
        jobs += [("story-desktop", story, 1920, 1080, 0, None),
                 ("story-perspectives", story, 1920, 1080, ".dist", ".dist .bubble"),
                 ("story-mobile", story, 390, 844, ".perspectives", None)]
    if topic:
        jobs.append(("topic", topic, 1440, 900, 0, None))

    OUT.mkdir(parents=True, exist_ok=True)
    done = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for name, page_path, w, h, scroll, hover in jobs:
            mobile = w < 600
            page = await browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=2 if mobile else 1)
            await page.goto((SITE / page_path).as_uri())
            await page.wait_for_timeout(600)
            if isinstance(scroll, str):
                await page.evaluate("(sel) => { const el = document.querySelector(sel); if (el) window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 140); }", scroll)
                await page.wait_for_timeout(300)
            if hover and await page.query_selector(hover):
                await page.hover(hover)
                await page.wait_for_timeout(300)
            png = OUT / f"{name}.png"
            await page.screenshot(path=str(png))
            await page.close()
            img = Image.open(png).convert("RGB")
            if img.width > 1600:
                img = img.resize((1600, round(img.height * 1600 / img.width)), Image.LANCZOS)
            img.save(OUT / f"{name}.jpg", quality=82, optimize=True)
            png.unlink()
            done.append(name)
        await browser.close()
    return done


def main() -> None:
    if not (SITE / "index.html").exists():
        raise SystemExit("Zuerst die Website bauen: python -m site_builder.build")
    done = asyncio.run(_shoot())
    print(f"{len(done)} Screenshots gespeichert in {OUT}: {', '.join(done)}")


if __name__ == "__main__":
    main()
