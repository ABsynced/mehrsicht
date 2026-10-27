"""Download each outlet's small logo (its website icon) once.

Saved in data/media/logos/<id>.png and reused on every run.
If an outlet has no usable icon, the site shows its first letter instead.
"""
from __future__ import annotations

import io
import logging
import re
from urllib.parse import urljoin, urlparse

import requests

from . import config

log = logging.getLogger(__name__)

LOGO_DIR = config.MEDIA_DIR / "logos"
ICON_LINK = re.compile(r"<link[^>]+rel=[\"'][^\"']*(apple-touch-icon|icon)[^\"']*[\"'][^>]*>", re.I)
HREF = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)


def site_of(source: dict) -> str:
    if source.get("site"):
        return source["site"].rstrip("/")
    host = urlparse(source["rss"]).hostname or ""
    parts = host.split(".")
    domain = ".".join(parts[-3:]) if host.endswith((".co.uk", ".com.au")) else ".".join(parts[-2:])
    return f"https://www.{domain}"


def _candidates(site: str) -> list[str]:
    urls = []
    try:
        html = requests.get(site, timeout=15, headers={"User-Agent": config.USER_AGENT}).text[:200_000]
        for tag in ICON_LINK.finditer(html):
            href = HREF.search(tag.group(0))
            if href:
                urls.append(urljoin(site + "/", href.group(1)))
    except requests.RequestException:
        pass
    # apple-touch-icons are bigger and look better, so they go first
    urls.sort(key=lambda u: 0 if "apple" in u.lower() else 1)
    return urls + [f"{site}/apple-touch-icon.png", f"{site}/favicon.ico"]


def fetch_logo(source: dict) -> str | None:
    from PIL import Image

    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    target = LOGO_DIR / f"{source['id']}.png"
    if target.exists():
        return f"media/logos/{target.name}"
    for url in _candidates(site_of(source)):
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": config.USER_AGENT})
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
            img = img.convert("RGBA")
            if min(img.size) < 16:
                continue
            img.thumbnail((96, 96))
            img.save(target, "PNG")
            return f"media/logos/{target.name}"
        except Exception:  # not an image, 404, unsupported format …
            continue
    log.info("Kein Logo für %s gefunden – zeige Anfangsbuchstaben", source["id"])
    return None


def fetch_all_logos(sources: list[dict], offline: bool) -> dict[str, str]:
    if offline:
        return {}
    logos = {}
    for s in sources:
        logo = fetch_logo(s)
        if logo:
            logos[s["id"]] = logo
    return logos
