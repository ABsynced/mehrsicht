"""Step 4: pick a photo for each story. Every story gets a DIFFERENT photo.

Two sources, set with IMAGE_SOURCE in .env (tried in this order):

  feed     The real news photo that the outlet put into its RSS feed, with
           the photographer/agency named when the feed provides it.
           ⚠ These photos are copyrighted (AP, dpa, Reuters, ...). Use this
           only on your own computer (private use, demos). NOT for a public site.

  commons  Free photos: first the main photo of the Wikipedia article about a
           person, place or organisation in the story, then a search on
           Wikimedia Commons. Only licences that allow
           reuse and editing: public domain, CC0, CC BY, CC BY-SA ("NC" and
           "ND" are rejected). Safe for the public website.

If nothing fits, the site shows the topic illustration instead.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re

import requests

from . import config
from .textutil import STOPWORDS, clean_html

log = logging.getLogger(__name__)

API = "https://commons.wikimedia.org/w/api.php"
BAD_WORDS = ("logo", "map", "karte", "flag", "flagge", "wappen", "coat of arms", "diagram", "chart", "icon", "svg", "signature")
# A centre outlet's photo is preferred, then left, then right (keeps the choice neutral).
BUCKET_ORDER = {"M": 0, "L": 1, "R": 2}


# ---------------------------------------------------------------- licences
def licence_ok(short_name: str) -> bool:
    name = (short_name or "").lower()
    parts = re.split(r"[\s\-]", name)
    if not name or "nc" in parts or "nd" in parts:
        return False
    return name.startswith(("cc0", "cc by", "public domain", "pd"))


def score(info: dict, title: str) -> float:
    """Higher is better: large, landscape, not a logo or map."""
    width, height = info.get("width", 0), info.get("height", 1)
    if width < 900:
        return -1
    ratio = width / max(height, 1)
    if not 1.2 <= ratio <= 2.4:
        return -1
    if any(w in title.lower() for w in BAD_WORDS):
        return -1
    return min(width, 4000) / 4000 + (1 - abs(ratio - 1.6))


# ---------------------------------------------------------------- download
GOOD_WIDTH = 900   # wide enough for the big cards without looking blurry
MAX_WIDTH = 1600   # bigger files are scaled down (faster site)
OG_IMAGE = re.compile(r"<meta[^>]+(?:property|name)=[\"'](?:og:image(?::url)?|twitter:image)[\"'][^>]*>", re.I)
CONTENT = re.compile(r"content=[\"']([^\"']+)[\"']", re.I)


def download(url: str, story_id: str, referer: str | None = None) -> dict | None:
    """Download, check and save a picture. Returns {src, w, h} or None.

    Every picture gets its own file name (from its web address), so two
    stories can never overwrite each other's picture.
    """
    import io

    from PIL import Image

    config.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": config.USER_AGENT}
    if referer:
        headers["Referer"] = referer
    try:
        resp = requests.get(url, timeout=30, headers=headers)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        img.load()
    except Exception as exc:  # network error, not a picture, unsupported format
        log.info("Bild übersprungen (%s): %s", url[:80], exc)
        return None
    if img.width < 300 or img.height < 150:
        return None  # icon or tracking pixel
    img = img.convert("RGB")
    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg"
    img.save(config.MEDIA_DIR / name, "JPEG", quality=86, optimize=True)
    return {"src": f"media/{name}", "w": img.width, "h": img.height}


def og_image(article_url: str | None) -> str | None:
    """The big share picture that almost every news article declares in its page header.

    It is usually 1200 px wide or more – much sharper than the small RSS thumbnails.
    """
    if not article_url or not article_url.startswith("http"):
        return None
    try:
        resp = requests.get(article_url, timeout=15, headers={"User-Agent": config.USER_AGENT}, stream=True)
        head = resp.raw.read(400_000, decode_content=True).decode(resp.encoding or "utf-8", errors="ignore")
        resp.close()
    except Exception:
        return None
    for tag in OG_IMAGE.finditer(head):
        m = CONTENT.search(tag.group(0))
        if m and m.group(1).startswith("http"):
            return html.unescape(m.group(1))
    return None


# ---------------------------------------------------------------- feed photos
def from_feed(story: dict, used: set[str]) -> dict | None:
    """Try each outlet's article picture (sharp version first), never one used before."""
    articles = sorted(story["articles"], key=lambda a: BUCKET_ORDER.get(a["bucket"], 3))
    fallback = None
    for art in articles[:5]:
        for url in dict.fromkeys(u for u in (og_image(art.get("url")), art.get("image_url")) if u):
            if url in used:
                continue
            got = download(url, story["id"], referer=art.get("url"))
            if not got:
                continue
            candidate = (got, url, art)
            if got["w"] >= GOOD_WIDTH:
                return _press_image(*candidate, used)
            if not fallback or got["w"] > fallback[0]["w"]:
                fallback = candidate
    return _press_image(*fallback, used) if fallback else None


def _press_image(got: dict, url: str, art: dict, used: set[str]) -> dict:
    used.add(url)
    who = art.get("image_credit")
    return {
            **got,
            "remote_url": url,
            "page_url": art.get("url"),
            "author": who or art["source_name"],
            "licence": "Pressefoto",
            "kind": "press",
            "credit": f"Foto: {who} · via {art['source_name']}" if who else f"Foto: {art['source_name']}",
    }


# ---------------------------------------------------------------- Wikimedia
def _commons_image(page: dict, min_width: int = 900, allow_portrait: bool = False) -> tuple[float, dict] | None:
    """Turn one Commons API page into our image record, or None if it is not usable."""
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata", {})
    licence = meta.get("LicenseShortName", {}).get("value", "")
    title = page.get("title", "")
    if not licence_ok(licence) or title.lower().endswith((".svg", ".gif", ".tif", ".tiff", ".pdf")):
        return None
    if allow_portrait:
        width = info.get("width", 0)
        if width < min_width or any(w in title.lower() for w in BAD_WORDS):
            return None
        s = 1.0
    else:
        s = score(info, title)
        if s <= 0:
            return None
    return s, {
        "remote_url": info.get("thumburl") or info.get("url"),
        "page_url": info.get("descriptionurl"),
        "author": clean_html(meta.get("Artist", {}).get("value", "Unbekannt"))[:80],
        "licence": licence,
        "title": title.removeprefix("File:"),
        "kind": "free",
    }


def search_commons(query: str) -> list[dict]:
    """All usable pictures for a search, best first."""
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6, "gsrlimit": 20,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1200,
    }
    try:
        resp = requests.get(API, params=params, timeout=20, headers={"User-Agent": config.USER_AGENT})
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
    except (requests.RequestException, ValueError) as exc:
        log.warning("Commons-Suche fehlgeschlagen (%s): %s", query, exc)
        return []
    found = [r for r in (_commons_image(p) for p in pages.values()) if r]
    return [img for _, img in sorted(found, key=lambda f: f[0], reverse=True)]


# ---------------------------------------------------------------- Wikipedia
WIKI_API = "https://{lang}.wikipedia.org/w/api.php"


def wiki_lead_image(name: str, lang: str = "de") -> str | None:
    """File name of the main picture of a Wikipedia article – only if it is freely licensed."""
    params = {"action": "query", "format": "json", "titles": name, "prop": "pageimages",
              "piprop": "name", "pilicense": "free", "redirects": 1}
    try:
        resp = requests.get(WIKI_API.format(lang=lang), params=params, timeout=20,
                            headers={"User-Agent": config.USER_AGENT})
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
    except (requests.RequestException, ValueError):
        return None
    for page in pages.values():
        if page.get("pageimage"):
            return page["pageimage"]
    return None


def commons_file(file_name: str) -> dict | None:
    """Licence, author and address of one Commons file (people may be portrait format)."""
    params = {"action": "query", "format": "json", "titles": f"File:{file_name}", "prop": "imageinfo",
              "iiprop": "url|size|extmetadata", "iiurlwidth": 1200}
    try:
        resp = requests.get(API, params=params, timeout=20, headers={"User-Agent": config.USER_AGENT})
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
    except (requests.RequestException, ValueError):
        return None
    for page in pages.values():
        got = _commons_image(page, min_width=500, allow_portrait=True)
        if got:
            return got[1]
    return None


def from_wikipedia(story: dict, used: set[str]) -> dict | None:
    """Main photo of the Wikipedia article about a person, place or organisation in the story."""
    names = [n for n in ([story.get("location")] + list(story.get("entities") or [])) if isinstance(n, str) and n.strip()]
    seen = set()
    for name in names[:8]:
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        for lang in ("de", "en"):
            file_name = wiki_lead_image(name, lang)
            if not file_name:
                continue
            image = commons_file(file_name)
            if not image or image["remote_url"] in used:
                continue
            got = download(image["remote_url"], story["id"])
            if got:
                used.add(image["remote_url"])
                image.update(got)
                image["credit"] = f"Foto: {image['author']} / {image['licence']} · Wikimedia Commons"
                return image
            break
    return None


def keyword_query(story: dict) -> str:
    """Search words from the headline, e.g. 'Proteste Frankreich' (for stories without AI query)."""
    words = [w for w in re.findall(r"[A-ZÄÖÜ][\wäöüß\-]{3,}", story["title"]) if w.lower() not in STOPWORDS]
    return " ".join(words[:3])


def from_commons(story: dict, topic_cfg: dict, used: set[str]) -> dict | None:
    # 1) the photo of the person/place/organisation the story is about (Wikipedia)
    image = from_wikipedia(story, used)
    if image:
        return image
    # 2) a search on Wikimedia Commons, 3) the topic's default search words
    queries = [q for q in (story.get("commons_query"), keyword_query(story)) if q]
    queries += topic_cfg.get(story["topic"], {}).get("commons", [])
    for query in queries:
        for image in search_commons(query):
            if image["remote_url"] in used:
                continue  # already shown on another story
            got = download(image["remote_url"], story["id"])
            if got:
                used.add(image["remote_url"])
                image.update(got)
                image["credit"] = f"Foto: {image['author']} / {image['licence']} · Wikimedia Commons · bearbeitet"
                return image
    return None


def pick_image(story: dict, topic_cfg: dict, offline: bool, used: set[str] | None = None) -> dict | None:
    if offline:
        return None
    used = used if used is not None else set()
    for source in config.IMAGE_SOURCES:
        image = from_feed(story, used) if source == "feed" else from_commons(story, topic_cfg, used) if source == "commons" else None
        if image:
            return image
    return None
