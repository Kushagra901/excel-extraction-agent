"""
Record Extraction Agent.

Converts CleanRow objects (keyed by raw header) into final Record objects
keyed by canonical field name. Unmapped headers are preserved verbatim
(never dropped) so no data is silently lost -- they just won't line up
across sheets that phrase the same concept differently.

Handles the case where two raw headers map to the same canonical field
(e.g. both "Total" and "Amount Due" map to "amount") by keeping the first
non-empty value and recording the collision as an issue rather than
overwriting silently.
"""

from __future__ import annotations

import logging

from src.agents.data_cleaner import CleanRow
from src.core.models import ExtractionContext, FieldMapping, IssueSeverity, Record

logger = logging.getLogger("excel_agent.record_extractor")


class RecordExtractionAgent:
    def extract_records(
        self,
        clean_rows: list[CleanRow],
        schema_map: dict[str, FieldMapping],
        sheet_name: str,
        ctx: ExtractionContext,
    ) -> list[Record]:
        records: list[Record] = []

        for clean_row in clean_rows:
            data: dict = {}
            for raw_header, value in clean_row.values.items():
                mapping = schema_map.get(raw_header)
                key = mapping.canonical_field if (mapping and mapping.canonical_field) else raw_header

                if key in data and data[key] not in (None, ""):
                    if value not in (None, ""):
                        ctx.add_issue(
                            IssueSeverity.WARNING, sheet_name,
                            f"Column collision: both map to '{key}'; kept the first "
                            f"non-empty value, discarded value from '{raw_header}'.",
                            row=clean_row.source_row, column=raw_header,
                        )
                    continue  # keep first value, don't overwrite

                data[key] = value

            record = Record(
                data=data,
                source_sheet=sheet_name,
                source_row=clean_row.source_row,
                record_issues=list(clean_row.notes),
            )
            records.append(record)

        logger.info("Sheet '%s': extracted %d records.", sheet_name, len(records))
        return records
