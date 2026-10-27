"""Turn data/edition_*.json into a finished static website in site/.

Usage:  python -m site_builder.build
The result is plain HTML/CSS/JS that any web host can serve
(GitHub Pages, Netlify, ...). The German edition lives at the root,
the European edition in site/eu/.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from pipeline import config
from pipeline.textutil import slugify

HERE = Path(__file__).resolve().parent
SITE = config.ROOT / "site"
SHARE_DIR = config.DATA_DIR / "share"

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
BUCKET_NAMES = {"L": "eher links", "M": "Mitte", "R": "eher rechts"}
BUCKET_COLORS = {"L": "#2563EB", "M": "#A1A7B3", "R": "#EA580C"}


def date_de(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]}, {dt.day}. {MONTHS[dt.month - 1]} {dt.year}"


def ago(iso: str | None, now: datetime) -> str:
    """'vor 3 Std.' style relative time."""
    if not iso:
        return ""
    minutes = int((now - datetime.fromisoformat(iso)).total_seconds() // 60)
    if minutes < 1:
        return "gerade eben"
    if minutes < 60:
        return f"vor {minutes} Min."
    if minutes < 48 * 60:
        return f"vor {minutes // 60} Std."
    return f"vor {minutes // 1440} Tagen"


def shapes(kind: str) -> list[str]:
    """CSS for the simple topic illustrations (used when no photo exists)."""
    def sh(l, t, w, h, extra):
        return f"left: {l}%; top: {t}%; width: {w}%; height: {h}%; {extra}"
    W, L, G = "background: rgba(255,255,255,0.42)", "background: rgba(255,255,255,0.75)", "background: rgba(0,0,0,0.14)"
    roof = "; clip-path: polygon(50% 0, 100% 100%, 0 100%)"
    if kind == "dome":
        return [sh(0, 84, 100, 16, G), sh(28, 42, 44, 42, W + "; border-radius: 50% 50% 0 0 / 100% 100% 0 0"),
                sh(49.5, 24, 1, 60, L), sh(38, 50, 1, 34, L), sh(61, 50, 1, 34, L), sh(22, 80, 56, 5, L)]
    if kind == "house":
        return [sh(0, 84, 100, 16, G), sh(16, 54, 20, 30, W), sh(13, 32, 26, 23, W + roof), sh(40, 44, 20, 40, W),
                sh(37, 20, 26, 25, W + roof), sh(64, 58, 18, 26, W), sh(61, 38, 24, 21, W + roof)]
    if kind == "chart":
        return [sh(0, 84, 100, 16, G), sh(20, 58, 10, 26, W), sh(33, 42, 10, 42, W), sh(46, 50, 10, 34, W),
                sh(59, 26, 10, 58, W), sh(72, 36, 10, 48, W)]
    import math
    out = []
    for k in range(12):
        a = k * math.pi / 6
        out.append(f"width: 6%; aspect-ratio: 1; border-radius: 50%; background: #FFCC00; "
                   f"left: {47 + 26 * math.cos(a):.1f}%; top: {45 + 34 * math.sin(a):.1f}%")
    return out


def highlight(article: dict, factchecks: list[dict]) -> Markup:
    """Wrap fact-checked sentences of a teaser in clickable buttons."""
    text = article["summary"]
    out = escape(text)
    for idx, h in enumerate(article.get("highlights", [])):
        fc = factchecks[h["fc"]]
        target = f"{idx}-{article['source_id']}"
        button = Markup(
            f'<button type="button" class="fc-mark fc-mark--{fc["verdict_class"]}" data-fc-target="{target}" '
            f'aria-expanded="false" title="Faktencheck: {escape(fc["verdict"])}">{escape(h["text"])}</button>'
        )
        out = out.replace(escape(h["text"]), button, 1)
    return Markup(out)


def make_env() -> Environment:
    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html"]))
    env.filters["ago"] = ago
    env.filters["highlight"] = highlight
    env.globals["shapes"] = shapes
    return env


COUNTRY_NAMES = {"DE": "Deutschland", "AT": "Österreich", "CH": "Schweiz", "FR": "Frankreich", "IT": "Italien",
                 "ES": "Spanien", "PL": "Polen", "NL": "Niederlande", "BE": "Belgien", "GB": "Großbritannien"}
LEAN_COLUMNS = [(-2, "Links"), (-1, "Eher links"), (0, "Mitte"), (1, "Eher rechts"), (2, "Rechts")]
PAGE_SIZE = 12


def copy_static() -> None:
    assets = SITE / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    shutil.copytree(HERE / "static", assets)
    if config.MEDIA_DIR.exists():
        shutil.copytree(config.MEDIA_DIR, SITE / "media", dirs_exist_ok=True)
    if SHARE_DIR.exists():
        shutil.copytree(SHARE_DIR, SITE / "share", dirs_exist_ok=True)


def share_files(edition: str, story_id: str) -> dict:
    files = {}
    for kind in ("story", "factcheck", "number", "link"):
        path = SHARE_DIR / edition / story_id / f"{kind}.png"
        if path.exists():
            files[kind] = f"share/{edition}/{story_id}/{kind}.png"
    return files


def date_long(iso: str | None) -> str:
    return date_de(datetime.fromisoformat(iso)) if iso else ""


def importance(story: dict, now: datetime) -> float:
    """Many outlets + recent = important (used for the top of the homepage)."""
    import math
    if not story.get("last_seen"):
        return 0
    age = (now - datetime.fromisoformat(story["last_seen"])).total_seconds() / 3600
    return story["source_count"] * math.exp(-max(age, 0) / 18)


def related_stories(story: dict, stories: list[dict], limit: int = 4) -> list[dict]:
    mine = set(story.get("topic_slugs", [])) | {story.get("category_slug")}
    scored = []
    for other in stories:
        if other["id"] == story["id"]:
            continue
        shared = len(mine & (set(other.get("topic_slugs", [])) | {other.get("category_slug")}))
        if shared:
            scored.append((shared, other.get("last_seen") or "", other))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [o for _, _, o in scored[:limit]]


def lean_columns(story: dict, sources: dict) -> list[dict]:
    """Outlets in five columns from left to right, each with its headline (for the hover card)."""
    outlets = {}
    for a in story["articles"]:
        if a.get("is_repost"):
            continue
        o = outlets.setdefault(a["source_id"], {"first": a, "count": 0})
        o["count"] += 1
    cols = []
    for lean, label in LEAN_COLUMNS:
        members = []
        for sid, o in outlets.items():
            a = o["first"]
            a_lean = a.get("lean") if a.get("lean") is not None else {"L": -1, "M": 0, "R": 1}[a["bucket"]]
            a_lean = max(-2, min(2, round(a_lean)))
            if a_lean == lean:
                base = sources.get(sid, {"id": sid, "name": a["source_name"]})
                members.append({**base, "id": sid, "article_title": a["title"], "article_url": a["url"],
                                "article_count": o["count"]})
        cols.append({"lean": lean, "label": label, "outlets": members})
    return cols


def ownership_split(story: dict, categories: dict) -> list[dict]:
    outlets = {a["source_id"]: a.get("ownership") for a in story["articles"]}
    counts = {}
    for cat in outlets.values():
        counts[cat or "unbekannt"] = counts.get(cat or "unbekannt", 0) + 1
    total = sum(counts.values()) or 1
    rows = []
    for key, n in sorted(counts.items(), key=lambda x: -x[1]):
        c = categories.get(key, {"name": "Unbekannt", "color": "#A1A7B3", "info": ""})
        rows.append({"key": key, "name": c["name"], "color": c["color"], "info": c.get("info", ""), "count": n,
                     "pct": round(100 * n / total)})
    return rows


def countries_line(story: dict) -> str:
    countries = story.get("countries") or {}
    if not countries:
        return ""
    code, n = next(iter(countries.items()))
    name = COUNTRY_NAMES.get(code, code)
    if len(countries) == 1:
        return f"Alle Quellen aus {name} ({n})"
    return f"Quellen überwiegend aus {name} ({n} von {sum(countries.values())})"


def topic_lean(stories: list[dict]) -> dict:
    counts = {"L": 0, "M": 0, "R": 0}
    for s in stories:
        for k in counts:
            counts[k] += s["counts"][k]
    total = sum(counts.values()) or 1
    p = {"l": round(100 * counts["L"] / total), "r": round(100 * counts["R"] / total)}
    p["m"] = 100 - p["l"] - p["r"]
    if abs(p["l"] - p["r"]) < 12:
        text = "wird von linken und rechten Medien ähnlich oft behandelt."
    elif p["l"] > p["r"]:
        text = "wird häufiger von eher linken Medien behandelt."
    else:
        text = "wird häufiger von eher rechten Medien behandelt."
    return {"percents": p, "text": text}


def covered_most_by(stories: list[dict], sources: dict, limit: int = 5) -> list[dict]:
    counts = {}
    for s in stories:
        for sid in {a["source_id"] for a in s["articles"]}:
            counts[sid] = counts.get(sid, 0) + 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:limit]
    return [{**sources.get(sid, {"id": sid, "name": sid}), "stories": n} for sid, n in top]


def build() -> None:
    env = make_env()
    SITE.mkdir(exist_ok=True)
    copy_static()
    editions = {}
    for code in config.EDITIONS:
        path = config.DATA_DIR / f"edition_{code}.json"
        if path.exists():
            editions[code] = json.loads(path.read_text(encoding="utf-8"))
    if not editions:
        raise SystemExit("Keine Daten gefunden. Zuerst: python -m pipeline.run --offline")

    now = datetime.now(timezone.utc)
    year = now.year
    demo = any(d.get("offline") for d in editions.values())
    press_photos = any(d.get("press_photos") for d in editions.values())
    source_counts = {code: len(d["sources"]) for code, d in editions.items()}
    trending_all = {code: d.get("trending", []) for code, d in editions.items()}
    topic_slugs = {code: set(d.get("topics", {})) for code, d in editions.items()}

    for code, data in editions.items():
        prefix = "" if code == "de" else "eu/"
        out_dir = SITE / prefix
        for sub in ("geschichte", "thema"):
            (out_dir / sub).mkdir(parents=True, exist_ok=True)
        generated = datetime.fromisoformat(data["generated_at"])
        parl = data["parliament"]
        parties = {p["id"]: p for p in parl["groups"] + parl.get("other_parties", [])}
        sources = {s["id"]: s for s in data["sources"]}
        categories = data.get("ownership_categories", {})
        topics = data.get("topics", {})
        stories = data["stories"]
        by_id = {s["id"]: s for s in stories}
        for s in stories:
            s["share_files"] = share_files(code, s["id"])
            # Stories from the archive may be older than some fields: fill them in.
            s.setdefault("sides", {})
            s.setdefault("bullets", [])
            s.setdefault("framing_words", [])
            s.setdefault("factchecks", [])
            s.setdefault("parties", [])
            for a in s.get("articles", []):
                src = sources.get(a.get("source_id"), {})
                a.setdefault("lean", src.get("lean", {"L": -1, "M": 0, "R": 1}.get(a.get("bucket"), 0)))
                a.setdefault("ownership", src.get("ownership"))
                a.setdefault("owner", src.get("owner"))
                a.setdefault("country", src.get("country"))
                a.setdefault("reposts", [])
                a.setdefault("is_repost", False)
                a.setdefault("highlights", [])
                a.setdefault("summary", "")
        ranked = sorted(stories, key=lambda s: importance(s, now), reverse=True)
        hero = ranked[:5]
        hero_ids = {s["id"] for s in hero}
        recent = sorted(stories, key=lambda s: s.get("last_seen") or "", reverse=True)
        rest = [s for s in recent if s["id"] not in hero_ids]
        features = sorted(rest[:9], key=lambda s: ((s.get("image") or {}).get("w") or 0) >= 700, reverse=True)[:3]
        feature_ids = {s["id"] for s in features}
        # the list shows every story except the three photo cards above it (the carousel is a separate teaser)
        news_list = [s for s in recent if s["id"] not in feature_ids]
        topic_counts = {}
        for s in stories:
            topic_counts[s["topic"]] = topic_counts.get(s["topic"], 0) + 1
        topics_nav = [{"name": t, "count": c, "slug": slugify(t)} for t, c in sorted(topic_counts.items(), key=lambda x: -x[1])]

        def ctx(depth: int, page: str, **extra) -> dict:
            root = "../" * depth
            home = root + prefix + "index.html"
            other_home = root + ("index.html" if code == "eu" else "eu/index.html")
            ed = {"code": code, "label": "Europa-Ausgabe" if code == "eu" else "Deutschland-Ausgabe", "home": home,
                  "other_home": other_home, "other_label": "Deutschland-Ausgabe" if code == "eu" else "Europa-Ausgabe",
                  "base": root + prefix}
            base = dict(
                root=root, ed=ed, page=page, data=data, stories=stories, parties=parties, sources=sources,
                topics=topics, categories=categories, trending=data.get("trending", []), trending_all=trending_all,
                topics_nav=topics_nav, today=date_de(generated), updated=ago(data["generated_at"], now),
                now=now, year=year, demo=demo, press_photos=press_photos, site_url=config.SITE_URL,
                newsletter_action=config.NEWSLETTER_FORM_ACTION, contact_email=config.CONTACT_EMAIL,
                bucket_names=BUCKET_NAMES, bucket_colors=BUCKET_COLORS, page_size=PAGE_SIZE,
                story_url=lambda st: f"{root}{prefix}geschichte/{st['id']}.html",
                story_url_id=lambda sid: f"{root}{prefix}geschichte/{sid}.html",
                story_path=lambda st: f"{prefix}geschichte/{st['id']}.html",
                topic_url=lambda slug: f"{root}{prefix}thema/{slug}.html",
                topic_path=lambda slug: f"{prefix}thema/{slug}.html",
                # footer links: topic page if it exists in that edition, else the topic overview
                topic_url_de=lambda slug: f"{root}thema/{slug}.html" if slug in topic_slugs.get("de", ()) else f"{root}themen.html",
                topic_url_eu=lambda slug: f"{root}eu/thema/{slug}.html" if slug in topic_slugs.get("eu", ()) else f"{root}eu/themen.html",
                country_names=COUNTRY_NAMES,
                logo_url=lambda sid: (root + sources[sid]["logo"]) if sources.get(sid, {}).get("logo") else None,
                date_long=date_long,
                source_count_de=source_counts.get("de", 0), source_count_eu=source_counts.get("eu", 0),
            )
            base.update(extra)
            return base

        depth = 0 if code == "de" else 1
        (out_dir / "index.html").write_text(env.get_template("index.html").render(
            ctx(depth, "home", hero=hero, features=features, news_list=news_list)), encoding="utf-8")

        story_tpl = env.get_template("story.html")
        for s in stories:
            others = [o for o in recent if o["id"] != s["id"]]
            html = story_tpl.render(ctx(depth + 1, "story", s=s,
                                        related=related_stories(s, stories),
                                        columns=lean_columns(s, sources),
                                        owners=ownership_split(s, categories),
                                        countries=countries_line(s),
                                        story_topics=[topics[t] for t in [s.get("category_slug")] + s.get("topic_slugs", []) if t in topics],
                                        more=others))
            (out_dir / "geschichte" / f"{s['id']}.html").write_text(html, encoding="utf-8")

        topic_tpl = env.get_template("topic.html")
        from pipeline.trending import related_topics
        for slug, t in topics.items():
            t_stories = [by_id[i] for i in t["story_ids"] if i in by_id]
            html = topic_tpl.render(ctx(depth + 1, "topic", t=t, t_stories=t_stories,
                                        lean=topic_lean(t_stories), covered=covered_most_by(t_stories, sources),
                                        related=[topics[r] for r in related_topics(topics, slug)],
                                        total_sources=sum(s["source_count"] for s in t_stories),
                                        n_outlets=len({a["source_id"] for s in t_stories for a in s["articles"]})))
            (out_dir / "thema" / f"{slug}.html").write_text(html, encoding="utf-8")

        # small index for the "Für dich" page (rendered in the browser from followed topics)
        story_index = [{"id": s["id"], "title": s["title"], "path": f"{prefix}geschichte/{s['id']}.html",
                        "topics": [s.get("category_slug")] + s.get("topic_slugs", []), "topic": s["topic"],
                        "image": (s.get("image") or {}).get("src"), "p": s["percents"], "n": s["source_count"],
                        "ago": ago(s.get("last_seen"), now), "last": s.get("last_seen") or ""} for s in recent]
        for name in ("themen", "fuer-dich", "faktenchecks"):
            (out_dir / f"{name}.html").write_text(env.get_template(f"{name}.html").render(
                ctx(depth, name, story_index=story_index)), encoding="utf-8")

        if code == "de" or "de" not in editions:
            for name in ("methode", "impressum", "datenschutz", "unterstuetzen", "faq"):
                html = env.get_template(f"{name}.html").render(ctx(0, name))
                (SITE / f"{name}.html").write_text(html, encoding="utf-8")
        print(f"Ausgabe {code.upper()}: Startseite + {len(stories)} Geschichten + {len(topics)} Themenseiten")

    (SITE / ".nojekyll").write_text("", encoding="utf-8")  # tells GitHub Pages to serve files as they are
    print(f"Fertig: {SITE}")


if __name__ == "__main__":
    build()
