"""Small text helpers used by several modules (no AI involved)."""
from __future__ import annotations

import html
import re
import unicodedata

STOPWORDS = set("""
der die das den dem des ein eine einer eines einem einen und oder aber auch nicht nur noch schon
mit von vom zu zum zur im in ins am an auf aus bei bis für fuer gegen nach über ueber unter vor
wie was wer wo wann warum ist sind war waren wird werden wurde wurden hat haben hatte sein seine
ihr ihre sich so es er sie wir ihr man mehr sehr als dass daß um ab jetzt heute neue neuen neues
the a an and or of to in on for with from by at is are be was were this that
le la les un une des du de et en au aux pour sur dans par est
el los las del y que por con para
il lo gli di da per con che non
""".split())


def clean_html(text: str) -> str:
    """Remove HTML tags and entities from RSS teasers."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def truncate(text: str, limit: int = 320) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + " …"


def tokens(text: str) -> set[str]:
    """Lower-case content words, used for simple similarity checks."""
    words = re.findall(r"[A-Za-zÄÖÜäöüßÀ-ÿ0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def slugify(text: str, max_len: int = 60) -> str:
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "story"


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", text)
    return [p.strip() for p in parts if p.strip()]
