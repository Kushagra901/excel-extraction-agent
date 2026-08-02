"""
Output Formatter Agent.

Writes the five deliverables from a completed ExtractionContext:
  1. cleaned_data.csv     -- flat table, one row per record, union of all fields
  2. extracted_data.json  -- full structured records with source traceability
  3. schema_map.json      -- exactly how every raw header was interpreted
  4. extraction_report.md -- human-readable summary for a person to review
  5. error_log.txt        -- every logged issue, plain text, chronological
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import logging
from pathlib import Path

from src.core.models import ExtractionContext

logger = logging.getLogger("excel_agent.output_formatter")


class OutputFormatterAgent:
    def write_all(self, ctx: ExtractionContext, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_csv(ctx, output_dir / "cleaned_data.csv")
        self._write_json(ctx, output_dir / "extracted_data.json")
        self._write_schema_map(ctx, output_dir / "schema_map.json")
        self._write_error_log(ctx, output_dir / "error_log.txt")
        self._write_report(ctx, output_dir / "extraction_report.md")
        logger.info("All outputs written to %s", output_dir)

    # ------------------------------------------------------------------ #

    @staticmethod
    def _write_csv(ctx: ExtractionContext, path: Path) -> None:
        if not ctx.records:
            path.write_text("", encoding="utf-8")
            return

        fieldnames: list[str] = []
        for r in ctx.records:
            row_dict = r.to_dict()
            for key in row_dict:
                if key not in fieldnames:
                    fieldnames.append(key)

        # Keep source metadata columns at the end, for readability.
        for meta_col in ("_issues", "_source_row", "_source_sheet"):
            if meta_col in fieldnames:
                fieldnames.remove(meta_col)
                fieldnames.append(meta_col)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in ctx.records:
                flat_row = r.to_dict()
                if isinstance(flat_row.get("_issues"), list):
                    flat_row["_issues"] = "; ".join(flat_row["_issues"])
                writer.writerow(flat_row)

    @staticmethod
    def _write_json(ctx: ExtractionContext, path: Path) -> None:
        source_file = json.dumps(ctx.input_path)
        generated_at = json.dumps(dt.datetime.now().isoformat(timespec="seconds"))
        record_count = len(ctx.records)

        with open(path, "w", encoding="utf-8") as f:
            f.write("{\n")
            f.write(f'  "source_file": {source_file},\n')
            f.write(f'  "generated_at": {generated_at},\n')
            f.write(f'  "record_count": {record_count},\n')
            f.write('  "records": [\n')

            for i, record in enumerate(ctx.records):
                record_json = json.dumps(record.to_dict(), default=str)
                comma = "," if i < record_count - 1 else ""
                f.write(f"    {record_json}{comma}\n")

            f.write("  ]\n")
            f.write("}\n")

    @staticmethod
    def _write_schema_map(ctx: ExtractionContext, path: Path) -> None:
        payload = {
            sheet: {header: mapping.to_dict() for header, mapping in mappings.items()}
            for sheet, mappings in ctx.schema_maps.items()
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _write_error_log(ctx: ExtractionContext, path: Path) -> None:
        lines = []
        for issue in ctx.issues:
            loc = f"{issue.sheet}"
            if issue.row is not None:
                loc += f":row {issue.row}"
            if issue.column:
                loc += f":col '{issue.column}'"
            lines.append(f"[{issue.severity.value.upper():7s}] {loc} -- {issue.message}")
        path.write_text("\n".join(lines) if lines else "No issues logged.\n", encoding="utf-8")

    @staticmethod
    def _write_report(ctx: ExtractionContext, path: Path) -> None:
        lines: list[str] = []
        lines.append(f"# Extraction Report")
        lines.append("")
        lines.append(f"- **Source file:** `{ctx.input_path}`")
        lines.append(f"- **Generated:** {dt.datetime.now().isoformat(timespec='seconds')}")
        lines.append(f"- **Sheets processed:** {len(ctx.sheet_profiles)}")
        lines.append(f"- **Total records extracted:** {len(ctx.records)}")
        lines.append("")

        sparse_profiles = [p for p in ctx.sheet_profiles.values() if p.is_sparse]
        if sparse_profiles:
            lines.append("## ⚠️ Sparse Sheet Warning")
            lines.append("")
            for p in sparse_profiles:
                hdr_idx = p.header_row_index if p.header_row_index is not None else 0
                lines.append(
                    f"- **Sheet `{p.name}`**: Sheet is {p.sparse_ratio * 100:.0f}% empty "
                    f"(detected header row: {hdr_idx}). Verify that data was not missed."
                )
            lines.append("")

        truncated_profiles = [
            p for p in ctx.sheet_profiles.values()
            if any("truncated to" in note for note in p.notes)
        ]
        if truncated_profiles:
            lines.append("## ⚠️ Truncated Sheet Warning")
            lines.append("")
            for p in truncated_profiles:
                for note in p.notes:
                    if "truncated to" in note:
                        lines.append(f"- **Sheet `{p.name}`**: {note}")
            lines.append("")

        if ctx.sheet_overlap_report:
            lines.append("## Sheet Overlap Analysis")
            lines.append("")
            lines.append("| Sheet Pair | Shared Rows | Overlap % | Action Taken |")
            lines.append("|---|---|---|---|")
            for pair, rep in ctx.sheet_overlap_report.items():
                lines.append(
                    f"| `{pair}` | {rep['shared_row_count']} | {rep['overlap_percentage']:.1f}% | {rep['action_taken']} |"
                )
            lines.append("")

        if ctx.sheet_diffs:
            lines.append("## Sheet Comparison")
            lines.append("")
            lines.append("| Sheet Pair | Common Records | Only in A | Only in B | Overlap % |")
            lines.append("|---|---|---|---|---|")
            for diff in ctx.sheet_diffs:
                lines.append(
                    f"| `{diff.sheet_a}` vs `{diff.sheet_b}` | {diff.common_record_count} | "
                    f"{diff.only_in_a_count} | {diff.only_in_b_count} | {diff.overlap_percentage:.1f}% |"
                )
            lines.append("")
            for diff in ctx.sheet_diffs:
                if diff.modified_records:
                    lines.append(f"**Modified Field Differences (`{diff.sheet_a}` vs `{diff.sheet_b}`):**")
                    for m in diff.modified_records[:20]:
                        lines.append(
                            f"- Row A:{m['row_a']} vs B:{m['row_b']} — field '{m['field']}' differs: {m['val_a']} vs {m['val_b']}"
                        )
                    if len(diff.modified_records) > 20:
                        lines.append(f"- ...and {len(diff.modified_records) - 20} more field differences.")
                    lines.append("")

        if ctx.column_alignment and len(ctx.sheet_profiles) > 1:
            sheets = sorted(list(ctx.sheet_profiles.keys()))
            lines.append("## Cross-Sheet Column Alignment")
            lines.append("")
            headers_row = ["Canonical Field"] + [f"`{s}` Header" for s in sheets] + ["Aligned?"]
            lines.append("| " + " | ".join(headers_row) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers_row)) + " |")

            for field_name in sorted(ctx.column_alignment.keys()):
                sheet_map_dict = ctx.column_alignment[field_name]
                present_sheets = [s for s in sheets if s in sheet_map_dict]

                raw_headers_cells = [sheet_map_dict.get(s, "—") for s in sheets]

                # Determine status
                if len(present_sheets) < len(sheets):
                    status = f"⚠️ Only in {', '.join(present_sheets)}"
                else:
                    confidences = []
                    methods = []
                    for s in sheets:
                        raw_h = sheet_map_dict[s]
                        if s in ctx.schema_maps and raw_h in ctx.schema_maps[s]:
                            m = ctx.schema_maps[s][raw_h]
                            confidences.append(m.confidence)
                            methods.append(m.method)

                    if confidences and (max(confidences) - min(confidences)) > 0.3:
                        status = f"⚠️ Confidence diff ({min(confidences):.2f} - {max(confidences):.2f})"
                    else:
                        m_type = "exact" if all(m == "exact" for m in methods) else "fuzzy"
                        status = f"✅ Yes ({m_type})"

                row_cells = [f"`{field_name}`"] + raw_headers_cells + [status]
                lines.append("| " + " | ".join(row_cells) + " |")
            lines.append("")

        if ctx.column_profiles:
            avg_quality = sum(cp.quality_score for cp in ctx.column_profiles) / len(ctx.column_profiles)
            lines.append("## Data Profile")
            lines.append("")
            lines.append(f"**Overall Data Quality Score:** `{avg_quality:.1f}%`")
            lines.append("")
            lines.append("| Field | Records | Nulls | Unique | Quality | Notes |")
            lines.append("|---|---|---|---|---|---|")
            for cp in ctx.column_profiles:
                null_str = f"{cp.null_count} ({cp.null_percentage:.1f}%)"
                quality_str = f"{cp.quality_score:.1f}%"
                notes_parts = []
                if cp.min_value is not None and cp.max_value is not None:
                    notes_parts.append(f"Range: {cp.min_value} - {cp.max_value}")
                if cp.min_date is not None and cp.max_date is not None:
                    notes_parts.append(f"Dates: {cp.min_date} to {cp.max_date}")
                if cp.invalid_count > 0:
                    notes_parts.append(f"{cp.invalid_count} invalid format")
                notes_str = "; ".join(notes_parts) if notes_parts else "—"

                lines.append(
                    f"| `{cp.field_name}` | {cp.total_count} | {null_str} | {cp.unique_count} | {quality_str} | {notes_str} |"
                )
            lines.append("")

        for report in ctx.validation_reports:
            lines.append(f"## Sheet: `{report.sheet}`")
            lines.append("")
            lines.append(f"| Metric | Value |")
            lines.append(f"|---|---|")
            lines.append(f"| Raw data rows | {report.raw_row_count} |")
            lines.append(f"| Records extracted | {report.extracted_record_count} |")
            lines.append(f"| Rows dropped | {report.dropped_row_count} |")
            lines.append(f"| Duplicate records found | {report.duplicate_count} |")
            lines.append(f"| Suspicious values flagged | {report.suspicious_value_count} |")
            lines.append("")

            if report.dropped_reasons:
                lines.append("**Why rows were dropped:**")
                for reason, count in report.dropped_reasons.items():
                    lines.append(f"- `{reason}`: {count}")
                lines.append("")

            if report.field_confidence:
                lines.append("**Schema mapping confidence:**")
                lines.append("")
                lines.append("| Canonical Field | Confidence |")
                lines.append("|---|---|")
                for field, conf in sorted(report.field_confidence.items(),
                                           key=lambda kv: -kv[1]):
                    flag = " ⚠️ low confidence" if conf < 0.85 else ""
                    lines.append(f"| `{field}` | {conf:.2f}{flag} |")
                lines.append("")

            sheet_map = ctx.schema_maps.get(report.sheet, {})
            unmapped = [h for h, m in sheet_map.items() if not m.canonical_field]
            if unmapped:
                lines.append(f"**Unmapped headers (kept as-is, needs manual review):** "
                              f"{', '.join(f'`{h}`' for h in unmapped)}")
                lines.append("")

            if report.duplicate_row_refs:
                lines.append("**Duplicate row pairs (source_row references):**")
                for a, b in report.duplicate_row_refs[:20]:
                    lines.append(f"- row {a} ~ row {b}")
                if len(report.duplicate_row_refs) > 20:
                    lines.append(f"- ...and {len(report.duplicate_row_refs) - 20} more "
                                  f"(see extracted_data.json)")
                lines.append("")

        lines.append("## Cross-Sheet Duplicates")
        lines.append("")
        if ctx.cross_sheet_duplicates:
            lines.append(f"Found {len(ctx.cross_sheet_duplicates)} cross-sheet duplicate pair(s):")
            for ref1, ref2 in ctx.cross_sheet_duplicates[:20]:
                lines.append(f"- `{ref1}` ~ `{ref2}`")
            if len(ctx.cross_sheet_duplicates) > 20:
                lines.append(f"- ...and {len(ctx.cross_sheet_duplicates) - 20} more")
        else:
            lines.append("No cross-sheet duplicates found.")
        lines.append("")

        error_count = sum(1 for i in ctx.issues if i.severity.value == "error")
        warning_count = sum(1 for i in ctx.issues if i.severity.value == "warning")
        lines.append("## Issue Summary")
        lines.append("")
        lines.append(f"- Errors: {error_count}")
        lines.append(f"- Warnings: {warning_count}")
        lines.append(f"- See `error_log.txt` for the full chronological list.")
        lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
