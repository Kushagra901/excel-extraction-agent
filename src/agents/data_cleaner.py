"""
Data Cleaning Agent.

Takes the raw grid (post header-detection) and produces cleaned row
dictionaries, applying the correct normalization function per column based
on the Schema Mapping Agent's output. Along the way it:
  - drops rows that are pure separators (all blank / all placeholder nulls)
  - drops rows that are a repeated copy of the header (common when Excel
    exports concatenate multiple report sections into one sheet)
  - never silently drops a row without logging why

This agent does NOT decide what the final canonical output records look
like -- that is the Record Extraction Agent's job. This agent's output is
still keyed by RAW header text, one dict per surviving row.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.canonical_schema import CANONICAL_SCHEMA
from src.core.cleaning_rules import CLEANERS, is_placeholder_null, normalize_whitespace
from src.core.models import ExtractionContext, FieldMapping, IssueSeverity

logger = logging.getLogger("excel_agent.data_cleaner")


class CleanRow:
    __slots__ = ("source_row", "values", "field_valid", "notes")

    def __init__(self, source_row: int):
        self.source_row = source_row
        self.values: dict[str, Any] = {}
        self.field_valid: dict[str, bool] = {}
        self.notes: list[str] = []


class DataCleaningAgent:
    def clean_sheet(
        self,
        grid: list[list[Any]],
        header_row_idx: int,
        headers: list[str],
        schema_map: dict[str, FieldMapping],
        sheet_name: str,
        ctx: ExtractionContext,
    ) -> list[CleanRow]:
        data_rows = grid[header_row_idx + 1:]
        normalized_headers = [normalize_whitespace(h) or "" for h in headers]
        cleaned_rows: list[CleanRow] = []

        dropped_blank = 0
        dropped_repeated_header = 0
        dropped_malformed = 0

        for offset, raw_row in enumerate(data_rows):
            # Absolute 1-indexed row number in the original sheet (for traceability).
            source_row = header_row_idx + 2 + offset  # +1 for header itself, +1 for 1-indexing

            if self._is_blank_row(raw_row):
                dropped_blank += 1
                ctx.add_issue(IssueSeverity.INFO, sheet_name,
                               "Row dropped: every cell was blank or a placeholder null "
                               "(separator row).", row=source_row)
                continue

            if self._is_repeated_header(raw_row, normalized_headers):
                dropped_repeated_header += 1
                ctx.add_issue(IssueSeverity.INFO, sheet_name,
                               "Dropped a row that duplicates the header (likely a "
                               "concatenated section break).", row=source_row)
                continue

            if len(raw_row) < len(headers):
                # Pad short rows rather than dropping them -- ragged rows are common
                # when trailing empty cells get trimmed by Excel on save.
                raw_row = list(raw_row) + [None] * (len(headers) - len(raw_row))

            clean_row = CleanRow(source_row=source_row)
            row_had_any_value = False

            for col_idx, raw_header in enumerate(headers):
                if col_idx >= len(raw_row):
                    continue
                raw_value = raw_row[col_idx]
                mapping = schema_map.get(raw_header)
                value_type = "text"
                if mapping and mapping.canonical_field:
                    value_type = CANONICAL_SCHEMA[mapping.canonical_field]["value_type"]

                cleaner = CLEANERS.get(value_type, CLEANERS["text"])
                cleaned_value, valid, note = cleaner(raw_value)

                if cleaned_value is not None:
                    row_had_any_value = True

                clean_row.values[raw_header] = cleaned_value
                clean_row.field_valid[raw_header] = valid
                if note:
                    clean_row.notes.append(f"{raw_header}: {note}")
                    ctx.add_issue(IssueSeverity.WARNING, sheet_name, note,
                                  row=source_row, column=raw_header)
                if not valid and cleaned_value is not None:
                    ctx.add_issue(IssueSeverity.WARNING, sheet_name,
                                  f"Value present but failed validation for field type "
                                  f"'{value_type}'.", row=source_row, column=raw_header)

            if not row_had_any_value:
                dropped_malformed += 1
                ctx.add_issue(IssueSeverity.INFO, sheet_name,
                               "Row dropped: every cell was empty or an unparseable "
                               "placeholder after cleaning.", row=source_row)
                continue

            cleaned_rows.append(clean_row)

        logger.info(
            "Sheet '%s': cleaned %d rows (dropped %d blank, %d repeated-header, "
            "%d fully-malformed).",
            sheet_name, len(cleaned_rows), dropped_blank, dropped_repeated_header,
            dropped_malformed,
        )
        return cleaned_rows

    @staticmethod
    def _is_blank_row(row: list[Any]) -> bool:
        return all(is_placeholder_null(c) for c in row)

    @staticmethod
    def _is_repeated_header(row: list[Any], normalized_headers: list[str]) -> bool:
        if not normalized_headers:
            return False
        row_normalized = [normalize_whitespace(c) or "" for c in row[:len(normalized_headers)]]
        # Pad in case row is shorter.
        while len(row_normalized) < len(normalized_headers):
            row_normalized.append("")
        matches = sum(
            1 for a, b in zip(row_normalized, normalized_headers)
            if a.strip().lower() == b.strip().lower() and b.strip() != ""
        )
        meaningful_headers = sum(1 for h in normalized_headers if h.strip() != "")
        if meaningful_headers == 0:
            return False
        return (matches / meaningful_headers) >= 0.8
