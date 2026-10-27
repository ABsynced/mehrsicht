"""Step 3: describe each story — bullet-point summary, how each side frames it,
loaded words, people/places/topics (for trending + topic pages), location,
parties, and short texts for the share cards.

The left/centre/right split itself is NOT decided by the AI: it is counted
from the outlets' lean values in config/sources_*.yaml. The AI only
describes the language, which keeps the numbers checkable.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter

from .llm import LLM
from .textutil import STOPWORDS, jaccard, slugify, split_sentences, tokens

log = logging.getLogger(__name__)

SIDE_NAMES = {"L": "links", "M": "mitte", "R": "rechts"}

SYSTEM = """Du analysierst, wie verschiedene Medien über dasselbe Ereignis berichten.
Du bekommst Schlagzeilen und Anreißer, jeweils mit der politischen Einordnung des Mediums
(links, mitte, rechts). Sei strikt neutral, erfinde keine Fakten, die nicht in den Texten
stehen, und bewerte nicht, wer recht hat. Beschreibe nur Wortwahl, Schwerpunkte und
zitierte Akteure. Schreibe auf Deutsch, kurz und verständlich (Sprachniveau B2)."""

PROMPT = """Meldungen:
{articles}

Gib dieses JSON zurück:
{{
  "title": "neutrale Überschrift, höchstens 10 Wörter",
  "bullets": ["3 neutrale Stichpunkte: Was ist passiert? Je 1 Satz."],
  "sides": {{"links": ["1-2 Stichpunkte: Worauf legen eher linke Medien den Schwerpunkt?"],
             "mitte": ["1-2 Stichpunkte"], "rechts": ["1-2 Stichpunkte"]}},
  "framing_words": [{{"word": "auffälliges Wort aus den Texten", "side": "links|mitte|rechts"}}],
  "tone": "1 kurzer Satz zur Tonlage der Berichterstattung",
  "entities": ["3 bis 6 Namen, um die es geht: Personen, Länder, Orte, Organisationen oder konkrete Vorhaben (z. B. Friedrich Merz, Frankreich, Rentenpaket)"],
  "location": "Ort und Land des Ereignisses, z. B. Berlin, Deutschland (oder null)",
  "share_title": "Überschrift für Social Media, höchstens 8 Wörter",
  "number": "eine aussagekräftige Zahl aus den Texten (oder null)",
  "number_label": "1 Satz, was die Zahl bedeutet (oder null)",
  "claims": ["bis zu 3 überprüfbare Tatsachenbehauptungen aus den Texten, wörtlich"],
  "commons_query": "2-4 Suchwörter für ein passendes Foto (Gebäude, Ort oder Gegenstand, KEINE Personen)"
}}
Für eine Seite ohne Meldungen: leere Liste []."""

GENERIC = set("""Länder Land Bund Regierung Studie Kritik Streit Pläne Plan Debatte Zahl Jahr Jahre Woche
Tag Tage Menschen Kosten Fragen Frage Bericht Medien Kritiker Experten Ökonomen Opposition Koalition
Neue Neuer Neues Mehr Weniger Kommentar Meinung Interview Liveticker News Update Millionen Milliarden Prozent""".split())


# ------------------------------------------------------------------ numbers
def bucket_counts(articles: list[dict]) -> dict:
    """Count each outlet once per story, even if it published two articles."""
    per_source = {a["source_id"]: a["bucket"] for a in articles}
    counts = Counter(per_source.values())
    return {"L": counts.get("L", 0), "M": counts.get("M", 0), "R": counts.get("R", 0)}


def percents(counts: dict) -> dict:
    total = sum(counts.values()) or 1
    l = round(100 * counts["L"] / total)
    r = round(100 * counts["R"] / total)
    return {"l": l, "m": 100 - l - r, "r": r}


def blindspot(counts: dict) -> str | None:
    total = sum(counts.values())
    if total < 3:
        return None
    if counts["L"] / total >= 0.65 and counts["R"] == 0:
        return "R"  # the RIGHT barely covers it -> blind spot for right-leaning readers
    if counts["R"] / total >= 0.65 and counts["L"] == 0:
        return "L"
    return None


def find_parties(text: str, party_keywords: dict[str, list[str]]) -> list[str]:
    found = []
    for party, words in party_keywords.items():
        if any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words):
            found.append(party)
    return found


def mark_reposts(articles: list[dict]) -> None:
    """Agency texts (dpa, AFP …) are often published almost word for word by
    several outlets. The first one stays, the others are listed as 'übernommen'."""
    for a in articles:
        a["reposts"], a["is_repost"] = [], False
    for i, a in enumerate(articles):
        if a["is_repost"]:
            continue
        ta = tokens(a["title"])
        for b in articles[i + 1:]:
            if not b["is_repost"] and b["source_id"] != a["source_id"] and jaccard(ta, tokens(b["title"])) >= 0.75:
                b["is_repost"] = True
                a["reposts"].append(b["source_name"])


# ------------------------------------------------------------------ AI answer
def _text(value) -> str | None:
    """AI answers are not always the right type (e.g. 48 instead of "48"). Make it text."""
    if value is None or isinstance(value, (dict, list)):
        return None
    value = str(value).strip()
    return None if value.lower() in ("", "null", "none", "n/a") else value


def _texts(value, limit: int) -> list[str]:
    """A list of short texts, whatever shape the AI used (string or list)."""
    if isinstance(value, str):
        value = split_sentences(value)
    if not isinstance(value, list):
        return []
    out = [t for t in (_text(v) for v in value) if t]
    return out[:limit]


def _clean(a: dict, items: list[dict]) -> dict:
    """Bring every field of the AI answer into the shape the website expects."""
    sides = a.get("sides") if isinstance(a.get("sides"), dict) else {}
    words = []
    for w in a.get("framing_words") or []:
        if isinstance(w, dict) and _text(w.get("word")):
            side = w.get("side") if w.get("side") in ("links", "mitte", "rechts") else "mitte"
            words.append({"word": _text(w["word"]), "side": side})
    title = _text(a.get("title")) or items[0]["title"]
    bullets = _texts(a.get("bullets"), 4) or _texts(a.get("summary"), 3) or [items[0]["summary"]]
    entities = []
    for e in _texts(a.get("entities"), 6):
        if 2 < len(e) <= 40 and e.lower() not in {x.lower() for x in entities}:
            entities.append(e)
    return {
        "title": title,
        "bullets": bullets,
        "summary": bullets[0],
        "sides": {k: _texts(sides.get(k), 3) for k in ("links", "mitte", "rechts")},
        "framing_words": words[:8],
        "tone": _text(a.get("tone")),
        "entities": entities,
        "location": _text(a.get("location")),
        "share_title": _text(a.get("share_title")) or title,
        "number": _text(a.get("number")),
        "number_label": _text(a.get("number_label")),
        "claims": _texts(a.get("claims"), 3),
        "commons_query": _text(a.get("commons_query")),
    }


def offline_entities(items: list[dict], known: list[str]) -> list[str]:
    """Without AI: known names found in the texts, plus the key word most outlets use."""
    text = " ".join(i["title"] + " " + i["summary"] for i in items)
    names = [k for k in known if re.search(r"(?<![\wäöüß])" + re.escape(k) + r"(?![\wäöüß])", text)]
    per_word = Counter()
    for i in items:
        seen = set()
        for w in re.findall(r"\b[A-ZÄÖÜ][\wäöüß\-]{3,}\b", i["title"]):
            if w.lower() not in STOPWORDS and w not in GENERIC and w not in seen:
                seen.add(w)
                per_word[w] += 1
    names += [w for w, c in per_word.most_common(2) if c >= 2 and w not in names]
    return names[:5]


def _offline_analysis(items: list[dict], known: list[str]) -> dict:
    """Rule-based stand-in for the AI so the site works without an API key."""
    centre = [i for i in items if i["bucket"] == "M"]
    first = centre[-1] if centre else items[-1]
    bullets, seen = [], set()
    for i in [first] + items:
        for s in split_sentences(i["summary"]):
            key = frozenset(tokens(s))
            if s not in seen and key and not any(jaccard(key, tokens(b)) > 0.5 for b in bullets):
                bullets.append(s)
                seen.add(s)
        if len(bullets) >= 3:
            break
    sides = {}
    for bucket, name in SIDE_NAMES.items():
        side_items = [i for i in items if i["bucket"] == bucket]
        sides[name] = [split_sentences(i["summary"])[0] for i in side_items[:2] if i["summary"]]
    framing = []
    for bucket, name in SIDE_NAMES.items():
        words = Counter()
        for i in items:
            if i["bucket"] == bucket:
                for w in re.findall(r"\b[A-ZÄÖÜ][a-zäöüß]{4,}\b", i["title"] + " " + i["summary"]):
                    if w.lower() not in STOPWORDS:
                        words[w] += 1
        framing += [{"word": w, "side": name} for w, _ in words.most_common(2)]
    numbers = re.findall(r"\b\d[\d.,]*\s(?:Prozent|Milliarden Euro|Milliarden|Millionen|Sitze|Lehrkräfte)",
                         " ".join(i["summary"] for i in items))
    return {
        "title": first["title"], "bullets": bullets[:3], "sides": sides, "framing_words": framing,
        "tone": None, "entities": offline_entities(items, known), "location": None,
        "share_title": " ".join(first["title"].split()[:8]),
        "number": numbers[0].strip() if numbers else None, "number_label": None,
        "claims": [], "commons_query": None,
    }


def analyse(items: list[dict], llm: LLM, use_ai: bool, known: list[str]) -> tuple[dict, bool]:
    """Returns (analysis, made_by_ai)."""
    items = sorted(items, key=lambda i: i["published"] or "", reverse=True)
    if llm.available and use_ai:
        # At most 8 articles, teasers shortened: keeps each request small.
        lines = [f"- [{SIDE_NAMES[i['bucket']]}] {i['source_name']}: {i['title']} — {i['summary'][:220]}" for i in items[:8]]
        # The "fast" model writes summaries; the main model's daily budget is kept for grouping.
        answer = llm.json(SYSTEM, PROMPT.format(articles="\n".join(lines)), max_tokens=2200, fast=True)
        if isinstance(answer, dict) and _text(answer.get("title")):
            return _clean(answer, items), True
    return _clean(_offline_analysis(items, known), items), False


# ------------------------------------------------------------------ story
def build_story(articles: list[dict], topic: str, analysis: dict, by_ai: bool, *, story_id: str | None,
                party_keywords: dict, party_labels: dict, topic_cfg: dict, ownership: dict) -> dict:
    """Put everything about one story together (also used again for updated stories)."""
    articles = sorted(articles, key=lambda a: a.get("published") or "", reverse=True)
    for a in articles:
        own = ownership.get(a["source_id"], {})
        a["ownership"] = own.get("category")
        a["owner"] = own.get("owner")
    mark_reposts(articles)
    counts = bucket_counts(articles)
    tcfg = topic_cfg.get(topic, topic_cfg["Sonstiges"])
    dated = [a for a in articles if a.get("published")]
    first = min(dated, key=lambda a: a["published"]) if dated else articles[-1]
    all_text = " ".join(a["title"] + " " + a["summary"] for a in articles)
    if not story_id:
        digest = hashlib.sha1((topic + (first.get("published") or "") + first["url"]).encode()).hexdigest()[:6]
        story_id = f"{slugify(analysis['title'])}-{digest}"
    countries = Counter(a.get("country") or "DE" for a in {a["source_id"]: a for a in articles}.values())
    parties = find_parties(all_text, party_keywords)
    entities = list(analysis.get("entities") or [])
    for p in parties:  # parties are topics too (e.g. "SPD")
        label = party_labels.get(p)
        if label and label.lower() not in {e.lower() for e in entities}:
            entities.append(label)
    return {
        "id": story_id,
        "topic": topic,
        "illustration": tcfg["illustration"],
        "tint": tcfg["tint"],
        "title": analysis["title"],
        "summary": analysis["summary"],
        "bullets": analysis["bullets"],
        "sides": analysis["sides"],
        "framing_words": analysis["framing_words"],
        "tone": analysis.get("tone"),
        "entities": entities[:7],
        "location": analysis.get("location"),
        "share": {"title": analysis["share_title"], "number": analysis["number"], "number_label": analysis["number_label"]},
        "claims": analysis["claims"],
        "commons_query": analysis["commons_query"],
        "analysis": analysis,
        "ai": by_ai,
        "analysed_sources": sum(counts.values()),
        "counts": counts,
        "percents": percents(counts),
        "source_count": sum(counts.values()),
        "blindspot": blindspot(counts),
        "parties": parties,
        "first_seen": first.get("published"),
        "last_seen": max((a["published"] for a in dated), default=None),
        "first_reported": {"source_name": first["source_name"], "published": first.get("published")},
        "countries": dict(countries.most_common()),
        "articles": [
            {k: a.get(k) for k in ("source_id", "source_name", "bucket", "lean", "country", "title", "summary", "url",
                                   "published", "image_url", "image_credit", "ownership", "owner", "reposts", "is_repost")}
            for a in articles
        ],
    }
