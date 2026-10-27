"""Quick test: are the AI keys found, and does each provider answer?

Usage:  python -m pipeline.check_ai           (only checks the keys, no internet)
        python -m pipeline.check_ai --live    (also sends one tiny test request)
Keys are never printed.
"""
from __future__ import annotations

import argparse
import logging

from . import config
from .llm import Backend


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="eine kleine Testanfrage an jeden Anbieter senden")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)

    print("Reihenfolge der KI-Anbieter (LLM_PROVIDER):", ", ".join(config.LLM_PROVIDERS))
    found = 0
    for name in config.LLM_PROVIDERS:
        s = config.provider_settings(name)
        if s["needs_key"] and not s["api_key"]:
            print(f"  ✗ {name:<9} kein Schlüssel in .env")
            continue
        found += 1
        line = f"  ✓ {name:<9} Schlüssel gefunden · Modell {s['model']}"
        if args.live:
            backend = Backend(s)
            try:
                answer = backend.ask('Antworte nur mit JSON.', 'Gib {"ok": true} zurück.', 400, fast=True)
                line += " · Test: antwortet ✓" if "ok" in answer else f" · Test: seltsame Antwort: {answer[:60]}"
            except Exception as exc:
                line += f" · Test FEHLGESCHLAGEN: {str(exc)[:120]}"
        print(line)
    if config.provider_settings("cerebras")["api_key"] and "cerebras" not in config.LLM_PROVIDERS:
        print("\nHinweis: Du hast einen Cerebras-Schlüssel, aber 'cerebras' fehlt in LLM_PROVIDER.\n"
              "Ändere in .env die Zeile zu:  LLM_PROVIDER=groq,cerebras")
    print("\nAlles bereit." if found else "\nKeine KI aktiv – die Seite läuft dann ohne KI (nur Regeln).")


if __name__ == "__main__":
    main()
