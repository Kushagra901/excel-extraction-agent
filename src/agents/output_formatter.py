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
        rows = [r.to_dict() for r in ctx.records]
        if not rows:
            path.write_text("", encoding="utf-8")
            return

        fieldnames: list[str] = []
        for row in rows:
            for key in row:
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
            for row in rows:
                flat_row = dict(row)
                if isinstance(flat_row.get("_issues"), list):
                    flat_row["_issues"] = "; ".join(flat_row["_issues"])
                writer.writerow(flat_row)

    @staticmethod
    def _write_json(ctx: ExtractionContext, path: Path) -> None:
        payload = {
            "source_file": ctx.input_path,
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "record_count": len(ctx.records),
            "records": [r.to_dict() for r in ctx.records],
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

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

        error_count = sum(1 for i in ctx.issues if i.severity.value == "error")
        warning_count = sum(1 for i in ctx.issues if i.severity.value == "warning")
        lines.append("## Issue Summary")
        lines.append("")
        lines.append(f"- Errors: {error_count}")
        lines.append(f"- Warnings: {warning_count}")
        lines.append(f"- See `error_log.txt` for the full chronological list.")
        lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
