"""Shared settings and file paths for the whole pipeline.

Everything that other modules need to know about folders, API keys and
config files lives here, so there is exactly one place to change it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
FIXTURES_DIR = ROOT / "fixtures"
DATA_DIR = ROOT / "data"
MEDIA_DIR = DATA_DIR / "media"
CACHE_DIR = DATA_DIR / "cache"

load_dotenv(ROOT / ".env")

# ---- AI providers ----------------------------------------------------
# LLM_PROVIDER is a list, tried in order. When the first one hits its free
# daily limit, the pipeline automatically switches to the next one.
#   groq, cerebras  – free tiers, no credit card (default: "groq,cerebras")
#   ollama          – free, runs on your own computer
#   openai          – any other OpenAI-compatible service (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)
#   anthropic       – Claude (paid)
LLM_PROVIDERS = [p.strip().lower() for p in os.getenv("LLM_PROVIDER", "groq,cerebras").split(",") if p.strip()]

PROVIDERS = {
    #             base URL                          key variable         main model             fast model            pause (s)
    "groq":      ("https://api.groq.com/openai/v1", "GROQ_API_KEY",      "openai/gpt-oss-120b", "openai/gpt-oss-20b", 12),
    "cerebras":  ("https://api.cerebras.ai/v1",     "CEREBRAS_API_KEY",  "gpt-oss-120b",        "gpt-oss-120b",       13),
    "ollama":    ("http://localhost:11434/v1",      "",                  "qwen3:8b",            "qwen3:8b",           0),
    "openai":    ("",                               "LLM_API_KEY",       "",                    "",                   0),
    "anthropic": ("",                               "ANTHROPIC_API_KEY", "claude-sonnet-5-5",   "claude-haiku-5-5",   0),
}


def provider_settings(name: str) -> dict:
    """Settings for one provider. Optional overrides in .env, e.g. GROQ_MODEL=..."""
    base, key_var, model, fast, pause = PROVIDERS.get(name, PROVIDERS["openai"])
    up = name.upper()
    return {
        "name": name,
        "base_url": (os.getenv(f"{up}_BASE_URL") or (os.getenv("LLM_BASE_URL") if name == "openai" else "") or base).strip().rstrip("/"),
        "api_key": (os.getenv(key_var, "") if key_var else "").strip(),
        "model": (os.getenv(f"{up}_MODEL") or (os.getenv("LLM_MODEL") if name == "openai" else "") or model).strip(),
        "model_fast": (os.getenv(f"{up}_MODEL_FAST") or fast or model).strip(),
        "pause": float(os.getenv(f"{up}_PAUSE", pause)),
        "needs_key": bool(key_var),
    }


def ready_providers() -> list[str]:
    return [p for p in LLM_PROVIDERS if provider_settings(p)["api_key"] or not provider_settings(p)["needs_key"]]


_several = len(ready_providers()) > 1 or any(p in ("anthropic", "ollama") for p in ready_providers())
# How many stories per edition get a full AI analysis (the rest use rules).
AI_MAX_STORIES = int(os.getenv("AI_MAX_STORIES", "25" if _several else "10"))
# Newest headlines per outlet sent to the AI for grouping.
AI_ITEMS_PER_SOURCE = int(os.getenv("AI_ITEMS_PER_SOURCE", "15"))
# Where photos come from, tried in order (see pipeline/images.py):
#   feed    = real news photos from the RSS feeds (copyrighted: ONLY for local/private use)
#   commons = free Wikimedia photos (safe for the public website)
IMAGE_SOURCES = [s.strip().lower() for s in os.getenv("IMAGE_SOURCE", "feed,commons").split(",") if s.strip()]
FACTCHECK_API_KEY = os.getenv("FACTCHECK_API_KEY", "").strip()
NEWSLETTER_FORM_ACTION = os.getenv("NEWSLETTER_FORM_ACTION", "").strip()
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "").strip()  # for "Fehler melden" / "Quelle vorschlagen"
SITE_URL = os.getenv("SITE_URL", "").strip().rstrip("/")

USER_AGENT = "MehrsichtBot/1.0 (+https://github.com/ABsynced/mehrsicht)"

EDITIONS = ("de", "eu")

# Lean value -> bucket. Negative = left, 0 = centre, positive = right.
def lean_bucket(lean: float) -> str:
    if lean < 0:
        return "L"
    if lean > 0:
        return "R"
    return "M"


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_sources(edition: str, offline: bool) -> list[dict]:
    """Real outlets in live mode; fictional demo outlets in offline mode.

    Offline mode deliberately uses invented outlet names ("Medium A" ...)
    so demo headlines are never attributed to a real newspaper.
    """
    path = (FIXTURES_DIR / f"sources_demo_{edition}.yaml") if offline else (CONFIG_DIR / f"sources_{edition}.yaml")
    sources = load_yaml(path)["sources"]
    for src in sources:
        src["bucket"] = lean_bucket(src.get("lean", 0))
    return sources


def load_ownership() -> dict:
    return load_yaml(CONFIG_DIR / "ownership.yaml")["outlets"]


def load_ownership_categories() -> dict:
    return load_yaml(CONFIG_DIR / "ownership.yaml")["categories"]


def load_topics() -> dict:
    return load_yaml(CONFIG_DIR / "topics.yaml")


def load_parliament(edition: str) -> dict:
    return load_json(CONFIG_DIR / f"parliament_{edition}.json")
