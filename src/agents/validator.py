"""
Validation and QA Agent.

Runs after extraction, per sheet, to answer three questions a user always
asks about an automated extraction:
  1. Did I lose data, and why?
  2. Are there duplicates I should know about?
  3. Which fields/values should I personally double-check?

Nothing here mutates records -- this agent only observes and reports.
"""

from __future__ import annotations

import logging
from collections import Counter

from src.core.models import (
    ExtractionContext, FieldMapping, IssueSeverity, Record, ValidationReport,
)

logger = logging.getLogger("excel_agent.validator")


class ValidationAgent:
    def __init__(self, duplicate_key_fields: list[str]):
        self.duplicate_key_fields = duplicate_key_fields

    def validate(
        self,
        sheet_name: str,
        raw_row_count: int,
        records: list[Record],
        schema_map: dict[str, FieldMapping],
        ctx: ExtractionContext,
    ) -> ValidationReport:
        dropped_reasons = self._count_dropped_reasons(sheet_name, ctx)
        dropped_row_count = sum(dropped_reasons.values())

        duplicate_count, duplicate_refs = self._find_duplicates(records)

        suspicious_count = self._count_suspicious(sheet_name, records, ctx)

        field_confidence = {
            mapping.canonical_field: mapping.confidence
            for mapping in schema_map.values()
            if mapping.canonical_field
        }

        report = ValidationReport(
            sheet=sheet_name,
            raw_row_count=raw_row_count,
            extracted_record_count=len(records),
            dropped_row_count=dropped_row_count,
            dropped_reasons=dropped_reasons,
            duplicate_count=duplicate_count,
            duplicate_row_refs=duplicate_refs,
            suspicious_value_count=suspicious_count,
            field_confidence=field_confidence,
        )

        logger.info(
            "Sheet '%s' validation: %d raw rows -> %d records (%d dropped, %d duplicates, "
            "%d suspicious values).",
            sheet_name, raw_row_count, len(records), dropped_row_count,
            duplicate_count, suspicious_count,
        )
        return report

    # ------------------------------------------------------------------ #

    @staticmethod
    def _count_dropped_reasons(sheet_name: str, ctx: ExtractionContext) -> dict[str, int]:
        reasons = Counter()
        for issue in ctx.issues:
            if issue.sheet != sheet_name:
                continue
            msg = issue.message.lower()
            if "dropped a row" in msg or "row dropped" in msg:
                if "duplicates the header" in msg:
                    reasons["repeated_header_row"] += 1
                elif "blank" in msg or "separator" in msg:
                    reasons["blank_or_separator_row"] += 1
                elif "malformed" in msg or "unparseable" in msg:
                    reasons["empty_or_malformed"] += 1
                else:
                    reasons["other"] += 1
        return dict(reasons)

    def _find_duplicates(self, records: list[Record]) -> tuple[int, list[tuple[int, int]]]:
        seen: dict[str, int] = {}  # key value -> source_row of first occurrence
        dup_count = 0
        dup_refs: list[tuple[int, int]] = []

        for record in records:
            key_value = None
            for field in self.duplicate_key_fields:
                val = record.data.get(field)
                if val not in (None, ""):
                    key_value = f"{field}::{str(val).strip().lower()}"
                    break
            if key_value is None:
                continue  # no usable key field present in this record

            if key_value in seen:
                dup_count += 1
                dup_refs.append((seen[key_value], record.source_row))
            else:
                seen[key_value] = record.source_row

        return dup_count, dup_refs

    def find_cross_sheet_duplicates(self, records: list[Record]) -> tuple[int, list[tuple[str, str]]]:
        seen: dict[str, Record] = {}
        dup_count = 0
        dup_refs: list[tuple[str, str]] = []

        for record in records:
            key_value = None
            for field in self.duplicate_key_fields:
                val = record.data.get(field)
                if val not in (None, ""):
                    key_value = f"{field}::{str(val).strip().lower()}"
                    break
            if key_value is None:
                continue

            if key_value in seen:
                first_record = seen[key_value]
                if first_record.source_sheet != record.source_sheet:
                    dup_count += 1
                    dup_refs.append(
                        (
                            f"{first_record.source_sheet}:row {first_record.source_row}",
                            f"{record.source_sheet}:row {record.source_row}",
                        )
                    )
            else:
                seen[key_value] = record

        return dup_count, dup_refs

    @staticmethod
    def _count_suspicious(sheet_name: str, records: list[Record], ctx: ExtractionContext) -> int:
        suspicious = 0

        # Explicit rule-based checks.
        for record in records:
            amount = record.data.get("amount")
            if isinstance(amount, (int, float)) and amount < 0:
                suspicious += 1
                ctx.add_issue(IssueSeverity.WARNING, sheet_name,
                               f"Negative amount value ({amount}) -- verify this is intentional "
                               f"(e.g. a refund) and not a data error.",
                               row=record.source_row, column="amount")

        # Values that failed cleaner validation were already logged as WARNING
        # issues by the Data Cleaning Agent -- count those too so nothing is missed.
        suspicious += sum(
            1 for issue in ctx.issues
            if issue.sheet == sheet_name
            and issue.severity == IssueSeverity.WARNING
            and "failed validation" in issue.message.lower()
        )
        return suspicious
