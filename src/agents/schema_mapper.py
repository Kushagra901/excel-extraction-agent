"""
Schema Mapping Agent.

Maps raw, messy header strings to canonical field names using:
  1. Exact match (case/whitespace-insensitive) against known synonyms.
  2. Fuzzy string similarity (rapidfuzz if installed, difflib otherwise)
     against every synonym of every canonical field; best score wins.
  3. Optional local LLM suggestion, ONLY if fuzzy match is below the
     confidence threshold AND enable_local_llm is set.

A header that never clears the threshold stays unmapped -- it will still
appear in the output CSV/JSON under its raw name so no data is lost, but
it is flagged in schema_map.json for manual review.
"""

from __future__ import annotations

import difflib
import logging
import re

from src.core.canonical_schema import CANONICAL_SCHEMA
from src.core.models import FieldMapping

logger = logging.getLogger("excel_agent.schema_mapper")

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize(text: str) -> str:
    return _NORMALIZE_RE.sub(" ", text.strip().lower()).strip()


def _similarity(a: str, b: str) -> float:
    if _HAS_RAPIDFUZZ:
        return _rapidfuzz_fuzz.ratio(a, b) / 100.0
    return difflib.SequenceMatcher(None, a, b).ratio()


class SchemaMapperAgent:
    def __init__(self, threshold: float = 0.72, enable_local_llm: bool = False,
                 llm_model: str = "llama3.1"):
        self.threshold = threshold
        self.enable_local_llm = enable_local_llm
        self.llm_model = llm_model
        # Pre-normalize synonyms once for speed.
        self._synonym_index: dict[str, list[str]] = {
            field: [_normalize(s) for s in meta["synonyms"]]
            for field, meta in CANONICAL_SCHEMA.items()
        }

    def map_headers(self, headers: list[str]) -> dict[str, FieldMapping]:
        result: dict[str, FieldMapping] = {}
        for raw_header in headers:
            result[raw_header] = self._map_single_header(raw_header)
        return result

    def _map_single_header(self, raw_header: str) -> FieldMapping:
        if raw_header is None or str(raw_header).strip() == "":
            return FieldMapping(raw_header=str(raw_header), canonical_field=None,
                                 confidence=0.0, method="unmapped")

        norm_header = _normalize(str(raw_header))

        # 1. Exact match against any synonym.
        for field, synonyms in self._synonym_index.items():
            if norm_header in synonyms:
                return FieldMapping(raw_header=raw_header, canonical_field=field,
                                     confidence=1.0, method="exact")

        # 2. Fuzzy match: best score across all fields' synonyms.
        best_field, best_score = None, 0.0
        for field, synonyms in self._synonym_index.items():
            for syn in synonyms:
                score = _similarity(norm_header, syn)
                if score > best_score:
                    best_field, best_score = field, score

        if best_score >= self.threshold:
            return FieldMapping(raw_header=raw_header, canonical_field=best_field,
                                 confidence=best_score, method="fuzzy")

        # 3. Optional local LLM fallback for genuinely ambiguous headers.
        if self.enable_local_llm:
            from src.core.llm_optional import suggest_canonical_field
            suggestion = suggest_canonical_field(
                raw_header, list(CANONICAL_SCHEMA.keys()), model=self.llm_model
            )
            if suggestion and suggestion in CANONICAL_SCHEMA:
                logger.info("Local LLM mapped header '%s' -> '%s'", raw_header, suggestion)
                return FieldMapping(raw_header=raw_header, canonical_field=suggestion,
                                     confidence=0.6, method="llm")

        logger.warning("Header '%s' could not be mapped confidently (best guess: %s, score: %.2f)",
                        raw_header, best_field, best_score)
        return FieldMapping(raw_header=raw_header, canonical_field=None,
                             confidence=best_score, method="unmapped")
