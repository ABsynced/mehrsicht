"""Connection to the AI models. Always returns parsed JSON (or None).

Several providers can be listed (LLM_PROVIDER=groq,cerebras). They are used
in that order: when one reaches its free DAILY limit or keeps failing, the
next one takes over automatically. If all are used up, the pipeline
continues with its rule-based mode, so the site still builds.
"""
from __future__ import annotations

import json
import logging
import re
import time

import requests

from . import config

log = logging.getLogger(__name__)


class RateLimited(Exception):
    def __init__(self, wait: int, daily: bool):
        super().__init__(f"rate limited ({'daily' if daily else 'per minute'})")
        self.wait, self.daily = wait, daily


class Backend:
    """One AI provider (e.g. Groq) with its own pacing and counters."""

    def __init__(self, settings: dict):
        self.__dict__.update(settings)
        self.exhausted = False
        self.last_call = 0.0
        self.calls = 0
        self.tokens = 0
        self.json_mode = True        # some providers reject response_format -> switched off automatically
        self.reasoning_param = True  # same for reasoning_effort
        self.client = None
        if self.name == "anthropic" and self.api_key:
            import anthropic  # only needed for the paid Claude API
            self.client = anthropic.Anthropic(api_key=self.api_key)

    @property
    def usable(self) -> bool:
        return not self.exhausted and (bool(self.api_key) or not self.needs_key)

    def pace(self) -> None:
        """Wait between requests so we stay under the free per-minute limits."""
        wait = self.pause - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        self.last_call = time.monotonic()

    def ask(self, system: str, user: str, max_tokens: int, fast: bool) -> str:
        model = self.model_fast if fast else self.model
        if self.name == "anthropic":
            return self._anthropic(system, user, max_tokens, model)
        return self._openai_compatible(system, user, max_tokens, model)

    def _openai_compatible(self, system: str, user: str, max_tokens: int, model: str) -> str:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_param and "gpt-oss" in model:
            body["reasoning_effort"] = "low"  # less hidden "thinking" = fewer tokens used
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = requests.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=120)
        if resp.status_code == 429:
            text = resp.text.lower()
            daily = any(w in text for w in ("per day", "tpd", "rpd", "daily", "quota"))
            wait = min(int(float(resp.headers.get("retry-after", "20") or 20)) + 1, 90)
            raise RateLimited(wait, daily)
        if resp.status_code == 400:
            text = resp.text.lower()
            # Provider does not know an optional parameter: drop it and try again.
            if "response_format" in text and self.json_mode:
                self.json_mode = False
                return self._openai_compatible(system, user, max_tokens, model)
            if "reasoning" in text and self.reasoning_param:
                self.reasoning_param = False
                return self._openai_compatible(system, user, max_tokens, model)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        self.calls += 1
        self.tokens += data.get("usage", {}).get("total_tokens", 0)
        return data["choices"][0]["message"]["content"]

    def _anthropic(self, system: str, user: str, max_tokens: int, model: str) -> str:
        import anthropic
        try:
            msg = self.client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                              messages=[{"role": "user", "content": user}])
        except anthropic.RateLimitError as exc:
            raise RateLimited(30, False) from exc
        self.calls += 1
        self.tokens += msg.usage.input_tokens + msg.usage.output_tokens
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


class LLM:
    def __init__(self, offline: bool = False):
        names = [] if offline else config.LLM_PROVIDERS
        self.backends = [Backend(config.provider_settings(n)) for n in names]
        self.backends = [b for b in self.backends if b.usable]

    @property
    def available(self) -> bool:
        return any(b.usable for b in self.backends)

    @property
    def calls(self) -> int:
        return sum(b.calls for b in self.backends)

    @property
    def tokens(self) -> int:
        return sum(b.tokens for b in self.backends)

    def describe(self) -> str:
        if not self.backends:
            return "ohne KI"
        return " → ".join(f"{b.name} · {b.model}" for b in self.backends)

    def usage(self) -> str:
        return ", ".join(f"{b.name}: {b.calls} Anfragen / {b.tokens} Tokens" for b in self.backends if b.calls)

    def json(self, system: str, user: str, max_tokens: int = 2000, fast: bool = False, retries: int = 3):
        """Ask the first usable provider; switch to the next one if it is used up."""
        system = system + "\n\nAntworte ausschließlich mit einem gültigen JSON-Objekt, ohne Erklärtext."
        for backend in self.backends:
            if not backend.usable:
                continue
            result = self._try(backend, system, user, max_tokens, fast, retries)
            if result is not None:
                return result
        return None

    def _try(self, backend: Backend, system: str, user: str, max_tokens: int, fast: bool, retries: int):
        for attempt in range(retries + 1):
            backend.pace()
            try:
                return _extract_json(backend.ask(system, user, max_tokens, fast))
            except RateLimited as exc:
                if exc.daily:
                    backend.exhausted = True
                    nxt = next((b.name for b in self.backends if b.usable), None)
                    log.warning("%s: Tageslimit erreicht – %s", backend.name,
                                f"wechsle zu {nxt}" if nxt else "Rest dieses Laufs ohne KI")
                    return None
                log.info("%s: Minutenlimit, warte %ds …", backend.name, exc.wait)
                time.sleep(exc.wait)
            except Exception as exc:  # network errors, bad JSON, ...
                log.warning("%s: Anfrage fehlgeschlagen (Versuch %d): %s", backend.name, attempt + 1, exc)
                time.sleep(3 * (attempt + 1))
        return None


def _extract_json(text: str):
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ValueError("Keine JSON-Antwort")
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    return value
