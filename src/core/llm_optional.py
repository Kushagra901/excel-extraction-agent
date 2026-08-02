"""
Optional local LLM assistance -- OFF by default.

This module is intentionally isolated: the entire deterministic pipeline
must work correctly if this file is deleted or Ollama is not running.
It is only consulted for individual, genuinely ambiguous headers that the
Schema Mapping Agent could not confidently map with fuzzy string matching.

Requires a local Ollama install (https://ollama.com) -- free, runs
entirely on your machine, no API key, no data leaves your network.
Enable with --enable-local-llm on the CLI, or `enable_local_llm: true`
in config.yaml.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger("excel_agent.llm_optional")

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.1"
TIMEOUT_SECONDS = 8


def _sanitize_header(header: str) -> str:
    """Sanitize raw header for inclusion in LLM prompt:
    - Truncate to max 100 characters.
    - Remove newlines, tabs, and control characters (ASCII < 32).
    - Replace double quotes with single quotes.
    """
    if not header:
        return ""
    truncated = header[:100]
    cleaned = "".join(c for c in truncated if ord(c) >= 32)
    return cleaned.replace('"', "'")


def suggest_canonical_field(raw_header: str, canonical_fields: list[str],
                             model: str = DEFAULT_MODEL) -> Optional[str]:
    """
    Ask a local model which canonical field (if any) a header most likely
    represents. Returns a canonical field name, "none", or None if the
    LLM call failed or Ollama isn't reachable -- callers must treat a
    None return the same as "stay unmapped", never as an error to crash on.
    """
    sanitized = _sanitize_header(raw_header)
    if sanitized != raw_header:
        logger.warning(
            "Sanitized header for LLM prompt: raw='%s' -> sanitized='%s'",
            raw_header, sanitized
        )

    prompt = (
        "You are helping map a messy spreadsheet column header to a canonical "
        "field name. Respond with EXACTLY ONE of these values and nothing else: "
        f"{', '.join(canonical_fields)}, or none.\n\n"
        f"Header: \"{sanitized}\"\n"
        "Canonical field:"
    )
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        answer = body.get("response", "").strip().lower()
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Local LLM unavailable or failed (%s) -- header '%s' stays unmapped.",
                        exc, raw_header)
        return None

    if answer == "none":
        return "none"
    for field in canonical_fields:
        if answer == field.lower():
            return field
    return None
