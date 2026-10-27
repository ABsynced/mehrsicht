"""Render social media images for every story with a headless browser.

Usage:  python -m sharecards.render
Creates data/share/<edition>/<story-id>/{story,factcheck,number,link}.png
  story / factcheck / number = 1080 x 1350 (Instagram, LinkedIn)
  link                       = 1200 x 630  (preview when a link is shared)

Rules built in: fact-check cards only use topic pictures and never a
photo marked as showing a person; every picture keeps its credit line.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pipeline import config
from site_builder.build import shapes

HERE = Path(__file__).resolve().parent
FONTS = (config.ROOT / "site_builder" / "static" / "fonts").as_uri()
OUT = config.DATA_DIR / "share"
STAMP = {"false": "#F87171", "misleading": "#FBBF24", "context": "#C4B5FD", "true": "#4ADE80"}
MAX_CARD_WORDS = 8


def cards_for(story: dict) -> list[tuple[str, dict]]:
    image = (config.DATA_DIR / story["image"]["src"]).as_uri() if story.get("image") else None
    credit = story["image"]["credit"] if story.get("image") else "Illustration: Mehrsicht"
    base = {"s": story, "image": image, "credit": credit, "shapes": shapes(story["illustration"]), "fonts": FONTS}
    title_words = len(story["share"]["title"].split())
    if title_words > MAX_CARD_WORDS:
        story = {**story, "share": {**story["share"], "title": " ".join(story["share"]["title"].split()[:MAX_CARD_WORDS]) + " …"}}
        base["s"] = story
    cards = [("story", {**base, "w": 1080, "h": 1350}), ("link", {**base, "w": 1200, "h": 630})]
    bad = [fc for fc in story.get("factchecks", []) if fc["verdict"] != "STIMMT"]
    if bad:
        fc = bad[0]
        cards.append(("factcheck", {**base, "w": 1080, "h": 1350, "fc": fc, "stamp_color": STAMP.get(fc["verdict_class"], "#fff")}))
    number = str(story["share"].get("number") or "").strip()
    label = str(story["share"].get("number_label") or "").strip()
    if not number or not label:
        number, label = str(story["source_count"]), "Medien berichten über diese Geschichte – so unterschiedlich erzählen sie sie."
    cards.append(("number", {**base, "w": 1080, "h": 1350, "number": number, "number_label": label}))
    return cards


def main() -> None:
    from playwright.sync_api import sync_playwright

    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=True)
    tpl = env.get_template("card.html")
    if OUT.exists():
        shutil.rmtree(OUT)
    tmp = config.DATA_DIR / "cache" / "cards"
    tmp.mkdir(parents=True, exist_ok=True)
    count = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for code in config.EDITIONS:
            path = config.DATA_DIR / f"edition_{code}.json"
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            for story in data["stories"]:
                target = OUT / code / story["id"]
                target.mkdir(parents=True, exist_ok=True)
                for kind, ctx in cards_for(story):
                    html_file = tmp / f"{kind}.html"
                    html_file.write_text(tpl.render(kind=kind, **ctx), encoding="utf-8")
                    page.set_viewport_size({"width": ctx["w"], "height": ctx["h"]})
                    page.goto(html_file.as_uri())
                    page.evaluate("document.fonts.ready")
                    page.screenshot(path=str(target / f"{kind}.png"))
                    count += 1
        browser.close()
    print(f"{count} Share-Kacheln erzeugt in {OUT.relative_to(config.ROOT)}")


if __name__ == "__main__":
    main()
