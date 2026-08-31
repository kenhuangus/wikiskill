"""LLM provider abstraction (design.md §4): protocol, OpenAI-compatible client, MockLLM."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any, List, Optional, Protocol


class LLM(Protocol):
    def chat(self, messages: List[dict], **kw) -> str: ...


def extract_json(text: str) -> Optional[Any]:
    """Extract the first JSON object/array from an LLM response (tolerates fences)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    for start_ch, end_ch in (("{", "}"), ("[", "]")):
        start = text.find(start_ch)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_ch:
                depth += 1
            elif text[i] == end_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        break
    return None


class OpenAICompatLLM:
    """Calls any OpenAI-compatible /chat/completions endpoint using stdlib urllib."""

    def __init__(self, model: str, base_url: Optional[str] = None,
                 api_key: Optional[str] = None, temperature: float = 0.7):
        self.model = model
        self.base_url = (base_url or os.environ.get("WIKISKILL_BASE_URL",
                         "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or os.environ.get("WIKISKILL_API_KEY",
                                                 os.environ.get("OPENAI_API_KEY", ""))
        self.temperature = temperature

    def chat(self, messages: List[dict], temperature: Optional[float] = None,
             max_tokens: int = 4096) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


class MockLLM:
    """Deterministic scripted LLM for tests and the offline demo.

    `handlers` maps a substring of the conversation to `(messages, call_log) -> str`.
    Fallback behaviour implements the demo dataset semantics.
    """

    def __init__(self, handlers: Optional[dict] = None):
        self.handlers = dict(handlers or {})
        self.call_log: List[dict] = []

    def chat(self, messages: List[dict], **kw) -> str:
        self.call_log.append({"messages": messages})
        blob = "\n".join(str(m.get("content", "")) for m in messages)
        for needle, fn in self.handlers.items():
            if needle in blob:
                return fn(messages, self.call_log)
        return self._fallback(blob)

    # ---- default demo behaviour -------------------------------------------
    def _fallback(self, blob: str) -> str:
        if "Wiki Maintainer Agent" in blob:
            return self._maintainer()
        if "Skill Proposer Agent" in blob:
            return self._proposer()
        return self._inference(blob)

    def _maintainer(self) -> str:
        return json.dumps({
            "create_patterns": [{
                "name": "rounding-errors.md",
                "content": ("# Pattern: Rounding errors\n\n## Description\n"
                            "Demo pattern: naive rounding gives wrong answers.\n\n"
                            "## Root cause\nSkipping the final rounding step.\n\n"
                            "## Workaround\nAlways round the final result to 2 decimals.\n"),
            }],
            "update_patterns": [],
            "update_index": ("- [rounding-errors](wiki/patterns/rounding-errors.md): "
                             "wrong answers from skipped rounding; FIX: round final "
                             "result to 2 decimals.\n"),
            "append_log": "Analyzed traces; recorded rounding-error pattern.",
        })

    def _proposer(self) -> str:
        return json.dumps({
            "action": "create",
            "skill": "unit-conversion",
            "content": ("---\nname: unit-conversion\ndescription: Correctly convert units "
                        "with exact arithmetic.\n---\n\n# Unit Conversion Skill\n\n"
                        "1. Compute using exact ratios.\n"
                        "2. Round ONLY the final result to 2 decimal places.\n"
                        "3. State the answer as `ANSWER: <value> <unit>`.\n"),
            "purpose": "Created from wiki pattern rounding-errors.md.",
        })

    def _inference(self, blob: str) -> str:
        # Demo tasks embed their correct answer as "expected=...". With the evolved
        # skill injected, the mock agent answers exactly; without it, it truncates
        # decimals (a systematic, deterministic "model weakness").
        m = re.search(r"expected=([-\d.]+)", blob)
        if not m:
            return "ANSWER: 0"
        val = m.group(1)
        if "round only the final result" in blob.lower():
            return f"ANSWER: {val}"
        whole, _, frac = val.partition(".")
        return "ANSWER: " + whole + "." + (frac[:1] if frac else "0")

