"""
Sheet Deduplicator Agent.

Compares sheets across the workbook to detect duplicate or overlapping content.
When two sheets have 100% row overlap (identical), it keeps records from one
sheet and removes duplicate records from the context.
When two sheets have partial overlap, it logs warning issues and records overlap details.
"""

from __future__ import annotations

import hashlib
import logging

from src.core.models import ExtractionContext, IssueSeverity, Record, SheetDiff

logger = logging.getLogger("excel_agent.sheet_deduplicator")


class SheetDeduplicatorAgent:
    def __init__(self, threshold: float = 0.8, duplicate_key_fields: list[str] | None = None):
        self.threshold = threshold
        self.duplicate_key_fields = duplicate_key_fields or ["email", "id", "full_name"]

    @staticmethod
    def _row_hash(record: Record) -> str:
        """Create a hash of a record's data values for identity comparison."""
        items = []
        for k, v in sorted(record.data.items()):
            if k.startswith("_"):
                continue
            val_str = "" if v is None else str(v).strip().lower()
            if val_str != "":
                items.append((k, val_str))
        serialized = str(items)
        return hashlib.md5(serialized.encode("utf-8")).hexdigest()

    def compare_sheets(self, sheet_a: str, sheet_b: str, ctx: ExtractionContext) -> SheetDiff:
        recs_a = [r for r in ctx.records if r.source_sheet == sheet_a]
        recs_b = [r for r in ctx.records if r.source_sheet == sheet_b]

        # Determine best key field
        key_field = None
        for candidate in self.duplicate_key_fields:
            has_in_a = any(candidate in r.data and r.data[candidate] is not None for r in recs_a)
            has_in_b = any(candidate in r.data and r.data[candidate] is not None for r in recs_b)
            if has_in_a or has_in_b:
                key_field = candidate
                break

        def _get_key(r: Record) -> str:
            if key_field and key_field in r.data and r.data[key_field] is not None:
                val = str(r.data[key_field]).strip().lower()
                if val != "":
                    return val
            return self._row_hash(r)

        keys_a_map: dict[str, list[Record]] = {}
        for r in recs_a:
            keys_a_map.setdefault(_get_key(r), []).append(r)

        keys_b_map: dict[str, list[Record]] = {}
        for r in recs_b:
            keys_b_map.setdefault(_get_key(r), []).append(r)

        set_keys_a = set(keys_a_map.keys())
        set_keys_b = set(keys_b_map.keys())

        common_keys = set_keys_a & set_keys_b
        only_a_keys = set_keys_a - set_keys_b
        only_b_keys = set_keys_b - set_keys_a

        common_row_refs: list[tuple[int, int]] = []
        modified_records: list[dict] = []

        for k in sorted(common_keys):
            r_a_list = keys_a_map[k]
            r_b_list = keys_b_map[k]
            for ra in r_a_list:
                for rb in r_b_list:
                    common_row_refs.append((ra.source_row, rb.source_row))
                    all_fields = set(ra.data.keys()) | set(rb.data.keys())
                    for f in sorted(all_fields):
                        if f.startswith("_"):
                            continue
                        val_a = ra.data.get(f)
                        val_b = rb.data.get(f)
                        str_a = "" if val_a is None else str(val_a).strip()
                        str_b = "" if val_b is None else str(val_b).strip()
                        if str_a != str_b:
                            modified_records.append({
                                "key": k,
                                "row_a": ra.source_row,
                                "row_b": rb.source_row,
                                "field": f,
                                "val_a": val_a,
                                "val_b": val_b,
                            })

        only_in_a_rows = sorted([r.source_row for k in only_a_keys for r in keys_a_map[k]])
        only_in_b_rows = sorted([r.source_row for k in only_b_keys for r in keys_b_map[k]])

        common_count = sum(len(keys_a_map[k]) for k in common_keys)
        only_in_a_count = sum(len(keys_a_map[k]) for k in only_a_keys)
        only_in_b_count = sum(len(keys_b_map[k]) for k in only_b_keys)

        total_unique = common_count + only_in_a_count + only_in_b_count
        overlap_percentage = round((common_count / total_unique * 100.0), 1) if total_unique > 0 else 0.0

        return SheetDiff(
            sheet_a=sheet_a,
            sheet_b=sheet_b,
            common_record_count=common_count,
            only_in_a_count=only_in_a_count,
            only_in_b_count=only_in_b_count,
            modified_records=modified_records,
            overlap_percentage=overlap_percentage,
            common_row_refs=common_row_refs,
            only_in_a_rows=only_in_a_rows,
            only_in_b_rows=only_in_b_rows,
        )

    def deduplicate(self, ctx: ExtractionContext) -> None:
        if not ctx.records:
            return

        # Group records by source_sheet
        records_by_sheet: dict[str, list[Record]] = {}
        for r in ctx.records:
            records_by_sheet.setdefault(r.source_sheet, []).append(r)

        sheets = list(records_by_sheet.keys())
        if len(sheets) < 2:
            return

        dropped_sheets: set[str] = set()

        for i in range(len(sheets)):
            for j in range(i + 1, len(sheets)):
                sheet_a = sheets[i]
                sheet_b = sheets[j]

                # Run sheet diff
                diff = self.compare_sheets(sheet_a, sheet_b, ctx)
                ctx.sheet_diffs.append(diff)

                if sheet_a in dropped_sheets or sheet_b in dropped_sheets:
                    continue

                recs_a = records_by_sheet[sheet_a]
                recs_b = records_by_sheet[sheet_b]

                if not recs_a or not recs_b:
                    continue

                # Header / canonical field check
                map_a = ctx.schema_maps.get(sheet_a, {})
                map_b = ctx.schema_maps.get(sheet_b, {})

                fields_a = {m.canonical_field for m in map_a.values() if m.canonical_field}
                fields_b = {m.canonical_field for m in map_b.values() if m.canonical_field}

                # If both sheets have canonical fields mapped and they are disjoint, skip row hashing
                if fields_a and fields_b and not (fields_a & fields_b):
                    pair_key = f"{sheet_a} vs {sheet_b}"
                    ctx.sheet_overlap_report[pair_key] = {
                        "sheet_a": sheet_a,
                        "sheet_b": sheet_b,
                        "overlap_percentage": 0.0,
                        "shared_row_count": 0,
                        "action_taken": "UNIQUE: Kept both",
                    }
                    continue

                hashes_a = [self._row_hash(r) for r in recs_a]
                hashes_b = [self._row_hash(r) for r in recs_b]

                set_a = set(hashes_a)
                set_b = set(hashes_b)
                shared_hashes = set_a & set_b
                shared_count = len(shared_hashes)

                min_len = min(len(recs_a), len(recs_b))

                if min_len == 0:
                    overlap_pct = 0.0
                else:
                    overlap_pct = round((shared_count / min_len) * 100, 1)

                pair_key = f"{sheet_a} vs {sheet_b}"

                # 1. IDENTICAL: 100% row overlap
                if len(recs_a) == len(recs_b) == shared_count and shared_count > 0:
                    dropped_sheets.add(sheet_b)
                    logger.info(
                        "Sheet '%s' is identical to '%s' (100%% overlap). Dropping %d duplicate records from '%s'.",
                        sheet_b, sheet_a, len(recs_b), sheet_b,
                    )
                    ctx.add_issue(
                        IssueSeverity.INFO,
                        sheet_b,
                        f"Sheet '{sheet_b}' is identical to '{sheet_a}' (100% overlap). Removed {len(recs_b)} duplicate records.",
                    )
                    ctx.sheet_overlap_report[pair_key] = {
                        "sheet_a": sheet_a,
                        "sheet_b": sheet_b,
                        "overlap_percentage": 100.0,
                        "shared_row_count": shared_count,
                        "action_taken": f"IDENTICAL: Merged (dropped {sheet_b})",
                    }
                # 2. PARTIAL OVERLAP
                elif shared_count > 0:
                    logger.warning(
                        "Cross-sheet overlap detected between '%s' and '%s': %d shared row(s) (%.1f%% overlap).",
                        sheet_a, sheet_b, shared_count, overlap_pct,
                    )
                    ctx.add_issue(
                        IssueSeverity.WARNING,
                        "<cross-sheet>",
                        f"Cross-sheet overlap detected between '{sheet_a}' and '{sheet_b}': {shared_count} matching row(s) (overlap: {overlap_pct}%).",
                    )
                    ctx.sheet_overlap_report[pair_key] = {
                        "sheet_a": sheet_a,
                        "sheet_b": sheet_b,
                        "overlap_percentage": overlap_pct,
                        "shared_row_count": shared_count,
                        "action_taken": "PARTIAL_OVERLAP: Flagged",
                    }
                # 3. UNIQUE
                else:
                    ctx.sheet_overlap_report[pair_key] = {
                        "sheet_a": sheet_a,
                        "sheet_b": sheet_b,
                        "overlap_percentage": 0.0,
                        "shared_row_count": 0,
                        "action_taken": "UNIQUE: Kept both",
                    }

        if dropped_sheets:
            ctx.records = [r for r in ctx.records if r.source_sheet not in dropped_sheets]
