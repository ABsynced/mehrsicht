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
    if not licence_ok(licence) or title.lower().endswith((".svg", ".gif", ".tif", ".tiff", ".pdf", ".webm", ".ogv")):
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
        "description": clean_html(meta.get("ImageDescription", {}).get("value", ""))[:160],
        "date": clean_html((meta.get("DateTimeOriginal") or meta.get("DateTime") or {}).get("value", ""))[:40],
        "kind": "free",
    }


def _get(url: str, params: dict) -> dict:
    try:
        resp = requests.get(url, params=params, timeout=20, headers={"User-Agent": config.USER_AGENT})
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.info("Bildsuche fehlgeschlagen (%s): %s", url[:40], exc)
        return {}


def search_commons(query: str) -> list[dict]:
    """All usable pictures for a Commons search, best first."""
    if not query:
        return []
    data = _get(API, {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6, "gsrlimit": 20,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1200,
    })
    pages = data.get("query", {}).get("pages", {})
    found = [r for r in (_commons_image(p) for p in pages.values()) if r]
    return [img for _, img in sorted(found, key=lambda f: f[0], reverse=True)]


# ---------------------------------------------------------------- Wikipedia
WIKI_API = "https://{lang}.wikipedia.org/w/api.php"


def wiki_lead_image(name: str, lang: str = "de") -> str | None:
    """File name of the main picture of a Wikipedia article – only if it is freely licensed."""
    data = _get(WIKI_API.format(lang=lang), {"action": "query", "format": "json", "titles": name,
                                             "prop": "pageimages", "piprop": "name", "pilicense": "free", "redirects": 1})
    for page in data.get("query", {}).get("pages", {}).values():
        if page.get("pageimage"):
            return page["pageimage"]
    return None


def wiki_lead_images(names: list[str], lang: str = "de") -> dict[str, str]:
    """Free main pictures of several Wikipedia articles in one request: {name: file}."""
    names = [n for n in dict.fromkeys(names) if n][:20]
    if not names:
        return {}
    data = _get(WIKI_API.format(lang=lang), {"action": "query", "format": "json", "titles": "|".join(names),
                                             "prop": "pageimages", "piprop": "name", "pilicense": "free", "redirects": 1})
    q = data.get("query", {})
    back = {}
    for step in ("normalized", "redirects"):
        for m in q.get(step, []):
            back[m["to"]] = back.get(m["from"], m["from"])
    out = {}
    for page in q.get("pages", {}).values():
        if page.get("pageimage") and "missing" not in page:
            title = page.get("title", "")
            out[back.get(title, title)] = page["pageimage"]
    return out


def wiki_search_images(query: str, lang: str = "de", limit: int = 6) -> list[tuple[str, str]]:
    """Search Wikipedia; return (article title, free lead image file) for the best matches."""
    if not query:
        return []
    data = _get(WIKI_API.format(lang=lang), {
        "action": "query", "format": "json", "generator": "search", "gsrsearch": query,
        "gsrlimit": limit, "gsrnamespace": 0, "prop": "pageimages", "piprop": "name", "pilicense": "free"})
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    return [(p.get("title", ""), p["pageimage"]) for p in pages if p.get("pageimage")]


def commons_files(file_names: list[str]) -> dict[str, dict]:
    """Licence, author, description and address for many Commons files in one request."""
    out = {}
    names = list(dict.fromkeys(f for f in file_names if f))
    for i in range(0, len(names), 40):
        chunk = names[i:i + 40]
        data = _get(API, {"action": "query", "format": "json", "titles": "|".join(f"File:{n}" for n in chunk),
                          "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1200})
        q = data.get("query", {})
        # the API may normalise names ("_" -> " "); map them back
        norm = {n["to"]: n["from"] for n in q.get("normalized", [])}
        for page in q.get("pages", {}).values():
            got = _commons_image(page, min_width=500, allow_portrait=True)
            if got:
                key = norm.get(page.get("title", ""), page.get("title", "")).removeprefix("File:")
                out[key] = got[1]
    return out


def commons_file(file_name: str) -> dict | None:
    return commons_files([file_name]).get(file_name)


# ---------------------------------------------------------------- choosing
def keyword_query(story: dict) -> str:
    """Search words from the headline, e.g. 'Proteste Frankreich' (for stories without AI query)."""
    words = [w for w in re.findall(r"[A-ZÄÖÜ][\wäöüß\-]{3,}", story["title"]) if w.lower() not in STOPWORDS]
    return " ".join(words[:4])


def _words(text: str) -> set[str]:
    from .textutil import tokens
    return tokens(text or "")


def relevance(story: dict, cand: dict) -> float:
    """How well a picture matches the story: shared words between the headline (+ main names)
    and the picture's article title / file name / description. German compounds count when
    one word starts with the other ('Supermarkt' ~ 'Supermarktkühlanlagen')."""
    story_words = _words(story["title"] + " " + (story.get("summary") or ""))
    pic_words = _words(" ".join([cand.get("article") or "", cand.get("title") or "", cand.get("description") or ""]))
    if not story_words or not pic_words:
        return 0.0
    hits = 0
    for w in story_words:
        if any(w == p or (len(w) >= 5 and len(p) >= 5 and (w.startswith(p) or p.startswith(w))) for p in pic_words):
            hits += 1
    return hits / len(story_words) ** 0.5


def headline_words(story: dict) -> list[str]:
    """Nouns and names from the headline ('Luftangriff', 'Saporischschja', 'Halloween')."""
    words = re.findall(r"[A-ZÄÖÜ][\wäöüß\-]{3,}", story["title"])
    return [w.strip("-") for w in dict.fromkeys(words) if w.lower() not in STOPWORDS][:5]


def candidates(story: dict, topic_cfg: dict) -> list[dict]:
    """Collect possible free photos for a story (no downloads yet), most specific first."""
    title_q = keyword_query(story)
    ai_q = story.get("commons_query")
    entities = [e for e in (story.get("entities") or []) if isinstance(e, str)]
    in_title = [e for e in entities if e.lower() in story["title"].lower()]
    # Full names of people in the headline: "Tusk" -> "Donald Tusk" if the AI named him fully.
    full = [e for e in entities if " " in e and any(e.lower().endswith(" " + w.lower()) for w in headline_words(story))]
    names = list(dict.fromkeys(full + in_title + ([story.get("location")] if story.get("location") else [])
                               + [w for w in headline_words(story) if not any(w in f for f in full)]))[:8]

    wiki_hits: list[tuple[str, str, str]] = []   # (article, file, how)
    for lang, query in (("de", title_q), ("de", ai_q if ai_q != title_q else None)):
        for article, file_name in wiki_search_images(query, lang):
            wiki_hits.append((article, file_name, "wikipedia-suche"))
    leads = wiki_lead_images(names, "de")
    missing = [n for n in names if n not in leads and (" " in n or n in in_title)]
    if missing:
        leads.update(wiki_lead_images(missing, "en"))
    for name in names:
        if name in leads:
            wiki_hits.append((name, leads[name], "wikipedia-thema"))
    files = commons_files([f for _, f, _ in wiki_hits])
    cands, seen = [], set()
    for article, file_name, how in wiki_hits:
        info = files.get(file_name)
        if info and info["remote_url"] not in seen:
            seen.add(info["remote_url"])
            cands.append({**info, "article": article, "how": how})
    for query in dict.fromkeys(q for q in (ai_q, title_q) if q):
        for info in search_commons(query)[:5]:
            if info["remote_url"] not in seen:
                seen.add(info["remote_url"])
                cands.append({**info, "article": "", "how": "commons-suche"})
    return cands


def topic_fallbacks(story: dict, topic_cfg: dict) -> list[dict]:
    """Generic photos for the topic (last resort, may repeat across stories). A result only
    counts if its file name or description contains one of the searched words."""
    out = []
    queries = topic_cfg.get(story["topic"], {}).get("commons", []) + ["Tageszeitungen Zeitungsstapel", "Reichstagsgebäude Berlin"]
    for query in queries:
        words = _words(query)
        for c in search_commons(query)[:8]:
            pic = _words(c.get("title", "") + " " + c.get("description", ""))
            if any(w == p or (len(w) >= 5 and (p.startswith(w[:6]) or w.startswith(p[:6]))) for w in words for p in pic):
                out.append({**c, "article": "", "how": "themenfoto"})
        if len(out) >= 6:
            break
    return out


OLD_YEAR = 1980  # photos from before this year are history, not news (unless the AI picks one on purpose)


def photo_year(c: dict) -> int | None:
    for text in (c.get("date") or "", c.get("title") or ""):
        m = re.search(r"\b(18\d\d|19\d\d|20\d\d)\b", text)
        if m:
            return int(m.group(1))
    return None


def ranked_candidates(story: dict, topic_cfg: dict, used: set[str]) -> list[dict]:
    """Unused candidates, best word match first; historical photos at the end."""
    cands = [c for c in candidates(story, topic_cfg) if c["remote_url"] not in used]
    order = {"wikipedia-thema": 0, "wikipedia-suche": 1, "commons-suche": 2}
    cands.sort(key=lambda c: ((photo_year(c) or 3000) < OLD_YEAR, -relevance(story, c), order.get(c["how"], 3)))
    return cands


AI_SYSTEM = (
    "Du bist Bildredakteur einer Nachrichtenseite. Für jede Nachricht bekommst du nummerierte freie Fotos. "
    "Wähle das Foto, das den Ort, das Ereignis, den Gegenstand oder die Hauptperson der Schlagzeile zeigt. "
    "Wähle KEINE Personen, die in der Schlagzeile nicht vorkommen, keine historischen Bilder ohne Bezug "
    "und keine Bilder, die nur zufällig ein Wort teilen. Wenn keins passt: pick 0. "
    "Gib außerdem immer 'query' an: 2-5 ENGLISCHE Suchwörter für ein passendes Foto auf Wikimedia Commons "
    "(Ort, Gebäude, Gegenstand oder Symbol des Themas; eine Person nur, wenn die Nachricht von ihr handelt). "
    'Antwort als JSON: {"S1": {"pick": 2, "query": "Warsaw constitutional tribunal building"}, "S2": {...}}'
)


def _describe(c: dict) -> str:
    parts = [f"Artikel: {c['article']}" if c.get("article") else "", f"Datei: {c['title']}",
             f"Beschreibung: {c['description'][:110]}" if c.get("description") else "",
             f"Jahr: {photo_year(c)}" if photo_year(c) else ""]
    return " | ".join(p for p in parts if p)


def ai_choose_batch(jobs: list[tuple[dict, list[dict]]], llm, per_request: int = 8) -> dict[str, dict]:
    """One AI request decides for up to 8 stories: {story_id: {"pick": index or -1, "query": str}}."""
    if not llm or not getattr(llm, "available", False):
        return {}
    decisions = {}
    for start in range(0, len(jobs), per_request):
        chunk = jobs[start:start + per_request]
        blocks = []
        for n, (story, cands) in enumerate(chunk, 1):
            lines = [f"  {i}. {_describe(c)}" for i, c in enumerate(cands[:6], 1)] or ["  (keine Fotos gefunden)"]
            blocks.append(f"### S{n}\nSchlagzeile: {story['title']}\nWorum es geht: {(story.get('summary') or '')[:200]}\nFotos:\n" + "\n".join(lines))
        answer = llm.json(AI_SYSTEM, "\n\n".join(blocks), max_tokens=1200, fast=True) or {}
        if not isinstance(answer, dict):
            continue
        for n, (story, cands) in enumerate(chunk, 1):
            row = answer.get(f"S{n}") or {}
            if not isinstance(row, dict):
                continue
            try:
                pick = int(row.get("pick") or 0)
            except (TypeError, ValueError):
                pick = 0
            pick = pick - 1 if 1 <= pick <= min(len(cands), 6) else -1
            query = str(row.get("query") or "").strip()[:80]
            decisions[story["id"]] = {"pick": pick, "query": query}
    return decisions


IMAGE_VERSION = 5      # new pictures get this number
KEEP_FROM_VERSION = 5  # older choices are made again once (a limited number per run)


def _take(story: dict, cand: dict, used: set[str], allow_reuse: bool = False, how: str | None = None) -> dict | None:
    if cand["remote_url"] in used and not allow_reuse:
        return None
    got = download(cand["remote_url"], story["id"])
    if not got:
        return None
    used.add(cand["remote_url"])
    image = {k: v for k, v in cand.items() if k not in ("description", "date")}
    image.update(got)
    image["v"] = IMAGE_VERSION
    if how:
        image["how"] = how
    image["credit"] = f"Foto: {image['author']} / {image['licence']} · Wikimedia Commons"
    return image


def _matches_query(c: dict, query: str) -> bool:
    words = _words(query)
    pic = _words(" ".join([c.get("title") or "", c.get("description") or ""]))
    return any(w == p or (len(w) >= 5 and len(p) >= 5 and (w.startswith(p[:6]) or p.startswith(w[:6]))) for w in words for p in pic)


def choose_images(stories: list[dict], topic_cfg: dict, used: set[str], llm=None) -> dict[str, dict]:
    """Choose a free photo for each story. Returns {story_id: image}."""
    jobs = [(s, ranked_candidates(s, topic_cfg, used)) for s in stories]
    decisions = ai_choose_batch(jobs, llm)
    chosen = {}
    for story, cands in jobs:
        d = decisions.get(story["id"])
        image = None
        # d["pick"] points into exactly the list the AI saw; _take refuses a photo another story took meanwhile
        if d and 0 <= d["pick"] < len(cands):
            image = _take(story, cands[d["pick"]], used)
            if image:
                image["how"] += "+ki"
        if not image and d and d.get("query"):
            # the AI's own search words for a fitting photo
            for c in search_commons(d["query"])[:8]:
                if _matches_query(c, d["query"]) and (photo_year(c) or 3000) >= OLD_YEAR:
                    image = _take(story, {**c, "article": ""}, used, how="ki-suche")
                    if image:
                        break
        if not image and not d:  # no AI available: trust a clear word match with a recent photo
            for c in cands:
                if relevance(story, c) <= 0:
                    break
                if (photo_year(c) or 3000) >= OLD_YEAR:
                    image = _take(story, c, used)
                    if image:
                        break
        if not image:  # nothing specific fits: a generic photo for the topic (may repeat)
            for c in topic_fallbacks(story, topic_cfg):
                image = _take(story, c, used, allow_reuse=True)
                if image:
                    break
        if image:
            chosen[story["id"]] = image
    return chosen


def from_free_sources(story: dict, topic_cfg: dict, used: set[str], llm=None) -> dict | None:
    return choose_images([story], topic_cfg, used, llm).get(story["id"])


def needs_new_image(image: dict | None) -> bool:
    """True if a story has no picture, an outdated choice, a missing file, or a press
    photo while press photos are not allowed (public website)."""
    if not image or not image.get("src") or not (config.DATA_DIR / image["src"]).exists():
        return True
    if image.get("kind") == "press":
        return "feed" not in config.IMAGE_SOURCES
    return (image.get("v") or 0) < KEEP_FROM_VERSION


def pick_image(story: dict, topic_cfg: dict, offline: bool, used: set[str] | None = None, llm=None) -> dict | None:
    if offline:
        return None
    used = used if used is not None else set()
    for source in config.IMAGE_SOURCES:
        if source == "feed":
            image = from_feed(story, used)
        elif source == "commons":
            image = from_free_sources(story, topic_cfg, used, llm)
        else:
            image = None
        if image:
            return image
    return None
