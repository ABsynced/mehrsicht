"""Offline end-to-end tests. Run with:  python -m pytest -q"""
import json

from pipeline import config
from pipeline.analyze import blindspot as _blindspot, percents as _percents, find_parties
from pipeline.factcheck import classify
from pipeline.images import licence_ok
from pipeline.run import run_edition
from pipeline.textutil import slugify
from pipeline.fetch import fetch_all


def _save_demo_edition(code="de"):
    """Build an offline demo edition and save it where the site builder looks."""
    data = run_edition(code, offline=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (config.DATA_DIR / f"edition_{code}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def test_licence_filter():
    assert licence_ok("CC BY-SA 4.0")
    assert licence_ok("CC0")
    assert licence_ok("Public domain")
    assert not licence_ok("CC BY-NC 2.0")
    assert not licence_ok("CC BY-ND 4.0")
    assert not licence_ok("")


def test_verdicts():
    assert classify("Falsch")[0] == "FALSCH"
    assert classify("Irreführend")[0] == "IRREFÜHREND"
    assert classify("Fehlender Kontext")[0] == "KONTEXT FEHLT"
    assert classify("Richtig")[0] == "STIMMT"


def test_percent_and_blindspot():
    assert _percents({"L": 1, "M": 1, "R": 1}) == {"l": 33, "m": 34, "r": 33}
    assert _blindspot({"L": 3, "M": 0, "R": 0}) == "R"
    assert _blindspot({"L": 1, "M": 1, "R": 1}) is None


def test_parties():
    kw = config.load_topics()["party_keywords"]
    assert set(find_parties("Union und SPD streiten mit der AfD", kw)) == {"CDU", "SPD", "AFD"}


def test_slug():
    assert slugify("Länder streiten über Größe") == "laender-streiten-ueber-groesse"


def test_offline_edition_de():
    data = run_edition("de", offline=True)
    assert data["offline"] and data["stories"]
    titles = " ".join(s["title"] for s in data["stories"])
    assert "Rentenpaket" in titles
    rente = next(s for s in data["stories"] if s["topic"] == "Rente")
    assert rente["source_count"] == 6
    assert any(fc["verdict"] == "FALSCH" for fc in rente["factchecks"])
    assert any(a["highlights"] for a in rente["articles"])
    assert data["disinfo"]["claim"].startswith("Die Rente")
    json.dumps(data)  # everything must be serialisable


def test_offline_edition_eu():
    data = run_edition("eu", offline=True)
    assert data["parliament"]["total"] == 720
    assert any(s["blindspot"] for s in data["stories"])


class FakeLLM:
    """Pretends to be Claude so the AI code path can be tested offline."""
    available = True

    calls = 0

    def json(self, system, user, max_tokens=4000, fast=False, retries=2):
        if "Schlagzeilen (Nummer|Medium|Titel)" in user:
            return {"items": {"0": "Rentenpaket im Bundestag", "1": "Rentenpaket im Bundestag",
                              "2": "Bundestag Rentenpaket Debatte"},
                    "events": {"Rentenpaket im Bundestag": "Rente"}}
        return {"title": "Bundestag streitet über Rentenpaket", "summary": "Der Bundestag debattiert.",
                "sides": {"links": "Schutz vor Armut.", "mitte": "Kosten erklärt.", "rechts": None},
                "framing_words": [{"word": "Zeche", "side": "rechts"}], "tone": "sachlich",
                "share_title": "Wer zahlt die Rente?", "number": "48 %", "number_label": "Rentenniveau",
                "claims": ["Die Rente wird halbiert"], "commons_query": "Bundestag Plenarsaal"}


def test_ai_path_with_fake_llm():
    from pipeline.analyze import analyse, build_story
    from pipeline.cluster import cluster
    from pipeline.fetch import fetch_all
    items = [i for i in fetch_all(config.load_sources("de", True), True, "de") if "Renten" in i["title"]][:3]
    for k, item in enumerate(items):
        item["n"] = k
    groups = cluster(items, list(config.load_topics()["topics"]), FakeLLM())
    assert groups and groups[0]["topic"] == "Rente"
    topics = config.load_topics()
    analysis, by_ai = analyse(groups[0]["items"], FakeLLM(), True, [])
    assert by_ai
    story = build_story(groups[0]["items"], groups[0]["topic"], analysis, by_ai, story_id=None,
                        party_keywords=topics["party_keywords"], party_labels={}, topic_cfg=topics["topics"], ownership={})
    assert story["title"] == "Bundestag streitet über Rentenpaket"
    assert story["share"]["number"] == "48 %"
    assert story["commons_query"] == "Bundestag Plenarsaal"


class FakeResponse:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code, self._payload, self.text, self.headers = status, payload, text, headers or {}

    def json(self):
        return self._payload


def make_llm(monkeypatch, responses, cerebras=False):
    """An LLM using Groq (and optionally Cerebras), with the network replaced by `responses`."""
    from pipeline import llm as llm_mod
    monkeypatch.setattr(llm_mod.config, "LLM_PROVIDERS", ["groq", "cerebras"])
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    if cerebras:
        monkeypatch.setenv("CEREBRAS_API_KEY", "csk_test")
    else:
        monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_PAUSE", "0")
    monkeypatch.setenv("CEREBRAS_PAUSE", "0")
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    sent = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append({"url": url, "body": dict(json), "headers": headers})
        return responses.pop(0)

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    return llm_mod.LLM(), sent


def make_groq(monkeypatch, responses):
    return make_llm(monkeypatch, responses)


def ok(content):
    return FakeResponse(200, {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 120}})


def test_groq_request_format(monkeypatch):
    llm, sent = make_groq(monkeypatch, [ok('{"title": "Test"}')])
    assert llm.available
    assert llm.json("sys", "user", fast=True) == {"title": "Test"}
    req = sent[0]
    assert req["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert req["headers"]["Authorization"] == "Bearer gsk_test"
    assert req["body"]["model"] == "openai/gpt-oss-20b"
    assert req["body"]["response_format"] == {"type": "json_object"}
    assert llm.tokens == 120


def test_groq_minute_limit_then_success(monkeypatch):
    limited = FakeResponse(429, text="Rate limit reached: tokens per minute (TPM)", headers={"retry-after": "5"})
    llm, sent = make_groq(monkeypatch, [limited, ok('{"a": 1}')])
    assert llm.json("s", "u") == {"a": 1}
    assert len(sent) == 2 and llm.available


def test_groq_daily_limit_falls_back(monkeypatch):
    daily = FakeResponse(429, text="Rate limit reached: tokens per day (TPD)")
    llm, _ = make_groq(monkeypatch, [daily])
    assert llm.json("s", "u") is None
    assert llm.available is False  # rest of the run uses the rule-based mode


def test_switches_to_cerebras_when_groq_is_used_up(monkeypatch):
    daily = FakeResponse(429, text="Rate limit reached: tokens per day (TPD)")
    llm, sent = make_llm(monkeypatch, [daily, ok('{"from": "cerebras"}'), ok('{"again": 1}')], cerebras=True)
    assert llm.json("s", "u") == {"from": "cerebras"}
    assert sent[1]["url"] == "https://api.cerebras.ai/v1/chat/completions"
    assert sent[1]["headers"]["Authorization"] == "Bearer csk_test"
    assert sent[1]["body"]["model"] == "gpt-oss-120b"
    # Groq stays switched off for the rest of the run; Cerebras answers directly.
    assert llm.json("s", "u") == {"again": 1}
    assert sent[2]["url"].startswith("https://api.cerebras.ai")


def test_all_providers_used_up(monkeypatch):
    daily = FakeResponse(429, text="tokens per day limit")
    llm, _ = make_llm(monkeypatch, [daily, FakeResponse(429, text="daily quota exceeded")], cerebras=True)
    assert llm.json("s", "u") is None
    assert llm.available is False


def test_drops_unsupported_json_mode(monkeypatch):
    bad = FakeResponse(400, text="Unsupported parameter: response_format")
    llm, sent = make_llm(monkeypatch, [bad, ok('{"ok": true}')])
    assert llm.json("s", "u") == {"ok": True}
    assert "response_format" not in sent[1]["body"]


def test_label_grouping_in_batches():
    """Headlines across several batches with the same label end up in one story."""
    from pipeline import cluster as cl

    class LabelLLM:
        available = True
        calls = 0

        def json(self, system, user, max_tokens=4000, fast=False, retries=2):
            out = {}
            for line in user.split("\n"):
                parts = line.split("|")
                if len(parts) == 3 and parts[0].isdigit():
                    t = parts[2].lower()
                    out[parts[0]] = ("Rentenpaket im Bundestag" if "rente" in t else
                                     "Heizungsgesetz neue Fristen" if "heizung" in t else "x")
            return {"items": out, "events": {"Rentenpaket im Bundestag": "Rente", "Heizungsgesetz neue Fristen": "Klima"}}

    items = fetch_all(config.load_sources("de", True), True, "de")
    old = cl.BATCH_SIZE
    cl.BATCH_SIZE = 5  # force several batches
    try:
        groups = cl.cluster_llm(items, list(config.load_topics()["topics"]), LabelLLM())
    finally:
        cl.BATCH_SIZE = old
    sizes = {g["topic"]: len({i["source_id"] for i in g["items"]}) for g in groups}
    assert sizes["Rente"] == 6 and sizes["Klima"] == 4


def test_ai_answer_with_wrong_types_is_cleaned():
    from pipeline.analyze import _clean
    items = [{"title": "T", "summary": "S"}]
    raw = {"title": "Titel", "summary": None, "number": 48, "number_label": "Prozent",
           "sides": {"links": "a", "rechts": None}, "framing_words": ["kaputt", {"word": "Last", "side": "rechts"}],
           "claims": ["Behauptung", {"x": 1}], "share_title": 123}
    out = _clean(raw, items)
    assert out["number"] == "48" and out["bullets"] == ["S"] and out["share_title"] == "123"
    assert out["framing_words"] == [{"word": "Last", "side": "rechts"}]
    assert out["claims"] == ["Behauptung"] and out["sides"]["mitte"] == [] and out["sides"]["links"] == ["a"]


FEED_WITH_IMAGES = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><title>X</title>
<item><title>Mit media:content</title><link>https://ex.org/1</link>
  <media:content url="https://img.ex.org/small.jpg" medium="image" width="300"/>
  <media:content url="https://img.ex.org/big.jpg" medium="image" width="1200"><media:credit>Ohad Zwigenberg/AP</media:credit></media:content>
</item>
<item><title>Mit enclosure</title><link>https://ex.org/2</link><enclosure url="https://img.ex.org/enc.jpg" type="image/jpeg" length="1"/></item>
<item><title>Bild im Text</title><link>https://ex.org/3</link><description>&lt;img src="https://img.ex.org/inline.jpg"&gt; Text</description></item>
<item><title>Ohne Bild</title><link>https://ex.org/4</link></item>
</channel></rss>"""


def test_feed_images_are_found():
    from pipeline.fetch import _parse
    items = _parse(FEED_WITH_IMAGES, {"id": "x", "name": "X", "bucket": "M"})
    urls = [i["image_url"] for i in items]
    assert urls == ["https://img.ex.org/big.jpg", "https://img.ex.org/enc.jpg", "https://img.ex.org/inline.jpg", None]
    assert items[0]["image_credit"] == "Ohad Zwigenberg/AP"


def test_each_story_gets_a_different_photo(monkeypatch):
    from pipeline import images
    monkeypatch.setattr(images, "download", lambda url, sid, referer=None: {"src": f"media/{sid}.jpg", "w": 1200, "h": 700})
    monkeypatch.setattr(images, "og_image", lambda url: None)
    same = {"image_url": "https://img/a.jpg", "image_credit": "dpa", "url": "u", "source_name": "S", "bucket": "M"}
    other = {"image_url": "https://img/b.jpg", "image_credit": None, "url": "u", "source_name": "T", "bucket": "L"}
    used = set()
    first = images.from_feed({"id": "s1", "articles": [same]}, used)
    second = images.from_feed({"id": "s2", "articles": [same, other]}, used)
    assert first["remote_url"] == "https://img/a.jpg" and first["credit"] == "Foto: dpa · via S"
    assert second["remote_url"] == "https://img/b.jpg" and second["credit"] == "Foto: T"


def test_sharp_article_picture_beats_small_thumbnail(monkeypatch):
    from pipeline import images
    sizes = {"https://big/og.jpg": 1400, "https://img/thumb.jpg": 320}
    monkeypatch.setattr(images, "og_image", lambda url: "https://big/og.jpg")
    monkeypatch.setattr(images, "download", lambda url, sid, referer=None: {"src": "media/x.jpg", "w": sizes[url], "h": 700})
    art = {"image_url": "https://img/thumb.jpg", "image_credit": None, "url": "https://news/1", "source_name": "S", "bucket": "M"}
    got = images.from_feed({"id": "s", "articles": [art]}, set())
    assert got["remote_url"] == "https://big/og.jpg" and got["w"] == 1400


def test_download_resizes_and_names_uniquely(monkeypatch, tmp_path):
    import io

    from PIL import Image

    from pipeline import images
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), "red").save(buf, "PNG")

    class Resp:
        content = buf.getvalue()

        def raise_for_status(self):
            pass

    monkeypatch.setattr(images.config, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(images.requests, "get", lambda *a, **k: Resp())
    a = images.download("https://x/1.png", "story")
    b = images.download("https://x/2.png", "story")
    assert a["w"] == 1600 and a["h"] == 1067 and a["src"] != b["src"]
    assert (tmp_path / a["src"].split("/")[1]).exists()


def test_archive_match_and_trending():
    from datetime import datetime, timezone, timedelta
    from pipeline import archive
    from pipeline.trending import build_topics, trending
    old = {"x1": {"id": "x1", "articles": [{"url": "u1"}, {"url": "u2"}, {"url": "u3"}]}}
    hit = archive.match([{"url": "u1"}, {"url": "u2"}, {"url": "new"}], old, set())
    assert hit and hit["id"] == "x1"
    assert archive.match([{"url": "zzz"}], old, set()) is None
    now = datetime.now(timezone.utc)
    stories = [
        {"id": "a", "topic": "Europa", "entities": ["Brüssel"], "source_count": 8, "last_seen": now.isoformat(), "image": None},
        {"id": "b", "topic": "Europa", "entities": ["Brüssel", "Polen"], "source_count": 2, "last_seen": (now - timedelta(hours=60)).isoformat(), "image": None},
        {"id": "c", "topic": "Klima", "entities": ["Polen"], "source_count": 1, "last_seen": (now - timedelta(hours=70)).isoformat(), "image": None},
    ]
    topics = build_topics(stories, ["Europa", "Klima"])
    assert "bruessel" in topics or "brussel" in topics
    rows = trending(stories, topics, now)
    assert rows[0]["name"] == "Brüssel"  # many recent outlets beat few old ones


def test_site_build_has_new_pages():
    from site_builder.build import build, SITE
    _save_demo_edition("de")
    build()
    assert (SITE / "themen.html").exists() and (SITE / "fuer-dich.html").exists() and (SITE / "faq.html").exists()
    assert any((SITE / "thema").glob("*.html"))
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'translate="no"' in html and "data-loadmore" in html


def test_trending_merges_names_and_skips_outlets():
    from datetime import datetime, timezone
    from pipeline.trending import build_topics, trending
    now = datetime.now(timezone.utc).isoformat()
    stories = [
        {"id": "a", "topic": "Ausland", "entities": ["Trump", "Euronews"], "source_count": 5, "last_seen": now, "image": None},
        {"id": "b", "topic": "Ausland", "entities": ["Donald Trump", "Euronews"], "source_count": 3, "last_seen": now, "image": None},
    ]
    topics = build_topics(stories, ["Ausland"], exclude=["Euronews", "euronews"])
    names = [r["name"] for r in trending(stories, topics, datetime.now(timezone.utc))]
    assert names == ["Donald Trump"]


def test_claimreview_parsing_and_matching():
    from pipeline.factfeeds import _claimreviews, _check, attach
    html = '''<script type="application/ld+json">{"@graph":[{"@type":"ClaimReview","claimReviewed":"Die EU verbietet Bargeld ab 2027",
      "reviewRating":{"alternateName":"Falsch"}}]}</script>'''
    rv = _claimreviews(html)
    assert rv and rv[0]["claimReviewed"].startswith("Die EU")
    fc = _check(rv[0]["claimReviewed"], rv[0]["reviewRating"]["alternateName"], title="t", url="u", publisher="p", date=None)
    assert fc["verdict"] == "FALSCH"
    story = {"title": "EU: Streit um Bargeld", "articles": [{"title": "Verbietet die EU das Bargeld?", "summary": "Gerüchte: ab 2027 kein Bargeld mehr in der EU."}]}
    assert attach(story, [fc])
    assert not attach({"title": "Fußball", "articles": [{"title": "Bayern gewinnt", "summary": ""}]}, [fc])


def test_factcheckers_config_loads():
    from pipeline.factfeeds import load_checkers
    names = [c["name"] for c in load_checkers("de")]
    assert "BR24 #Faktenfuchs" in names and len(load_checkers("eu")) >= 5


def test_impressum_from_settings(monkeypatch):
    from pipeline import config
    from site_builder.build import build, SITE
    _save_demo_edition("de")
    monkeypatch.setattr(config, "IMPRESSUM_NAME", "Erika Muster")
    monkeypatch.setattr(config, "IMPRESSUM_ADDRESS", ["Musterweg 1", "60311 Frankfurt"])
    build()
    html = (SITE / "impressum.html").read_text(encoding="utf-8")
    assert "Erika Muster" in html and "60311 Frankfurt" in html and "todo" not in html


def test_wikipedia_lead_image(monkeypatch, tmp_path):
    """The photo of a person in the story is found via Wikipedia, with licence and author."""
    from pipeline import images

    class Resp:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data

    def fake_get(url, params=None, **kw):
        if "wikipedia" in url:
            name = params["titles"]
            return Resp({"query": {"pages": {"1": {"pageimage": "Merz_2024.jpg"} if name == "Friedrich Merz" else {}}}})
        return Resp({"query": {"pages": {"2": {"title": "File:Merz_2024.jpg", "imageinfo": [{
            "width": 1200, "height": 1600, "thumburl": "https://upload.example/merz.jpg",
            "descriptionurl": "https://commons.example/Merz", "extmetadata": {
                "LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<a>Jane Doe</a>"}}}]}}}})

    monkeypatch.setattr(images.requests, "get", fake_get)
    monkeypatch.setattr(images, "download", lambda url, sid, referer=None: {"src": "media/x.jpg", "w": 900, "h": 1200})
    story = {"id": "s1", "location": None, "entities": ["Bundestag", "Friedrich Merz"]}
    img = images.from_wikipedia(story, set())
    assert img and img["licence"] == "CC BY-SA 4.0" and "Jane Doe" in img["credit"]


def test_non_free_or_svg_images_are_rejected():
    from pipeline.images import _commons_image
    page = {"title": "File:Flag_of_Germany.svg", "imageinfo": [{"width": 2000, "height": 1200,
            "extmetadata": {"LicenseShortName": {"value": "Public domain"}}}]}
    assert _commons_image(page, 500, True) is None
    page = {"title": "File:Photo.jpg", "imageinfo": [{"width": 2000, "height": 1200,
            "extmetadata": {"LicenseShortName": {"value": "CC BY-NC 2.0"}}}]}
    assert _commons_image(page, 500, True) is None
