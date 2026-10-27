"""Step 2: group headlines from different outlets that report the same event.

With AI: the model gives each headline a short event label (in batches);
headlines with the same label form one story.
Offline: headlines are grouped by word overlap (good enough for the demo).
"""
from __future__ import annotations

import logging
import re

from . import config
from .llm import LLM
from .textutil import jaccard, tokens

log = logging.getLogger(__name__)

SYSTEM = """Du bist Redakteur einer Nachrichten-Vergleichsseite. Du bekommst nummerierte
Schlagzeilen verschiedener Medien (auch in anderen Sprachen). Gib JEDER Schlagzeile ein kurzes
deutsches Ereignis-Kürzel (3 bis 6 Wörter), das das konkrete Ereignis benennt, z. B.
"Proteste in Frankreich gegen Macron" oder "Trump gibt Stimme für Midterms ab".
Schlagzeilen über DASSELBE Ereignis müssen EXAKT dasselbe Kürzel bekommen.
Gibt es schon ein passendes Kürzel in der Liste der bekannten Kürzel, verwende genau dieses.
Für Sport, Wetter, Promi-Klatsch, Kultur-Einzelmeldungen, Ratgeber und Liveticker: "x"."""

BATCH_SIZE = 40


def newest_per_source(items: list[dict], limit: int) -> list[dict]:
    """Keep only the newest `limit` headlines of each outlet (smaller AI request)."""
    by_source: dict[str, list[dict]] = {}
    for item in items:
        by_source.setdefault(item["source_id"], []).append(item)
    kept = []
    for group in by_source.values():
        group.sort(key=lambda i: i["published"] or "", reverse=True)
        kept.extend(group[:limit])
    return kept


def _norm(label: str) -> str:
    return " ".join(re.findall(r"[a-zäöüß0-9]+", (label or "").lower()))


def cluster_llm(items: list[dict], topics: list[str], llm: LLM) -> list[dict] | None:
    """The AI labels every headline with a short event name, in small batches.

    Labelling one headline at a time is a much easier job for a model than
    sorting 200 headlines into groups in one go, so the results are better.
    Headlines with the same label become one story.
    """
    items = newest_per_source(items, config.AI_ITEMS_PER_SOURCE)
    by_n = {i["n"]: i for i in items}
    labels: dict[int, str] = {}          # headline number -> event label
    label_topic: dict[str, str] = {}     # event label -> topic
    known: list[str] = []
    failed = 0
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        lines = [f"{i['n']}|{i['source_name']}|{i['title']}" for i in batch]
        user = (
            "Themenliste: " + ", ".join(topics) + "\n"
            "Bekannte Kürzel: " + ("; ".join(known[-80:]) if known else "(noch keine)") + "\n\n"
            "Schlagzeilen (Nummer|Medium|Titel):\n" + "\n".join(lines) + "\n\n"
            'Gib zurück: {"items": {"Nummer": "Kürzel oder x"}, '
            '"events": {"Kürzel": "Thema aus der Themenliste"}}'
        )
        result = llm.json(SYSTEM, user, max_tokens=3000)
        if not isinstance(result, dict) or not isinstance(result.get("items"), dict):
            failed += 1
            continue
        for key, label in result["items"].items():
            try:
                n = int(key)
            except (TypeError, ValueError):
                continue
            if n in by_n and isinstance(label, str) and _norm(label) not in ("", "x"):
                labels[n] = label.strip()
        for label, topic in (result.get("events") or {}).items():
            if isinstance(label, str):
                label_topic[_norm(label)] = topic if topic in topics else "Sonstiges"
        known = list(dict.fromkeys(known + [l for l in labels.values()]))
    if failed and failed * BATCH_SIZE >= len(items):
        return None  # nothing worked -> caller uses the offline rules

    # Same label (after normalising) = same story. Near-identical labels are merged too.
    norm_labels = sorted({_norm(l) for l in labels.values()})
    parent = {l: l for l in norm_labels}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x]
        return x

    for a_i, a in enumerate(norm_labels):
        for b in norm_labels[a_i + 1:]:
            if jaccard(set(a.split()), set(b.split())) >= 0.6:
                parent[find(a)] = find(b)

    buckets: dict[str, list[dict]] = {}
    for n, label in labels.items():
        buckets.setdefault(find(_norm(label)), []).append(by_n[n])
    groups = []
    for root, members in buckets.items():
        if len({m["source_id"] for m in members}) < 2:
            continue
        member_labels = {_norm(labels[m["n"]]) for m in members}
        topic = next((label_topic[l] for l in member_labels if l in label_topic), "Sonstiges")
        groups.append({"topic": topic, "items": members})
    return groups


def guess_topic(text: str, topic_keywords: dict[str, list[str]]) -> str:
    low = text.lower()
    best, score = "Sonstiges", 0
    for topic, words in topic_keywords.items():
        hits = sum(1 for w in words if w.lower() in low)
        if hits > score:
            best, score = topic, hits
    return best


# Keyword hints for the offline topic guess.
TOPIC_HINTS = {
    "Rente": ["rente", "rentner", "rentenpaket", "altersvorsorge"],
    "Haushalt": ["haushalt", "schuldenbremse", "etat", "finanzminister"],
    "Migration": ["geflüchtet", "flüchtling", "migration", "asyl", "asylpakt"],
    "Klima": ["heizung", "klima", "wärmepumpe", "klimaziel", "co2"],
    "Wohnen": ["miete", "mietpreisbremse", "wohnung", "wohnen"],
    "Wirtschaft": ["industrie", "aufträge", "konjunktur", "wirtschaft", "bürokratie", "industriepolitik"],
    "Bildung": ["lehrer", "schule", "bildung", "quereinst"],
    "Verteidigung": ["rüstung", "bundeswehr", "verteidigung"],
    "Handel": ["mercosur", "handel", "zoll", "abkommen"],
    "Europa": ["eu-", "brüssel", "gipfel", "kommission", "bargeld", "digitale euro"],
}


def cluster_offline(items: list[dict], threshold: float = 0.12) -> list[dict]:
    """Two items belong together if they share enough words (single linkage).

    Uses a small "union-find": every item starts in its own group, and
    groups are merged whenever two of their items are similar enough.
    """
    words = [tokens(i["title"] + " " + i["summary"]) for i in items]
    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            if items[a]["source_id"] != items[b]["source_id"] and jaccard(words[a], words[b]) >= threshold:
                parent[find(a)] = find(b)

    buckets: dict[int, list[dict]] = {}
    for idx, item in enumerate(items):
        buckets.setdefault(find(idx), []).append(item)
    result = []
    for members in buckets.values():
        if len({m["source_id"] for m in members}) < 2:
            continue
        text = " ".join(m["title"] + " " + m["summary"] for m in members)
        result.append({"topic": guess_topic(text, TOPIC_HINTS), "items": members})
    return result


def cluster(items: list[dict], topics: list[str], llm: LLM) -> list[dict]:
    if llm.available:
        groups = cluster_llm(items, topics, llm)
        if groups is not None:
            log.info("KI hat %d Geschichten gebildet", len(groups))
            return groups
        log.warning("KI-Gruppierung fehlgeschlagen, nutze Offline-Regeln")
    groups = cluster_offline(items)
    log.info("Offline-Regeln: %d Geschichten", len(groups))
    return groups
