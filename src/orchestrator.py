"""
Supervisor Agent (orchestrator).

Owns the end-to-end plan and runs every other agent in the correct order,
per sheet. This is the only file that knows the full pipeline shape --
every other agent only knows its own phase.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from src.agents.data_cleaner import DataCleaningAgent
from src.agents.data_profiler import DataProfilerAgent
from src.agents.excel_reader import ExcelReaderAgent
from src.agents.output_formatter import OutputFormatterAgent
from src.agents.record_extractor import RecordExtractionAgent
from src.agents.schema_mapper import SchemaMapperAgent
from src.agents.sheet_deduplicator import SheetDeduplicatorAgent
from src.agents.sqlite_writer import SQLiteWriterAgent
from src.agents.validator import ValidationAgent
from src.core.models import ExtractionContext, IssueSeverity
from src.utils.file_helpers import make_run_output_dir
from src.utils.logging_setup import close_logging, setup_logging

logger = logging.getLogger("excel_agent.orchestrator")


class Supervisor:
    def __init__(self, config: dict):
        self.config = config
        self.max_processing_time = self.config.get("max_processing_time_seconds", 300)

    def run(self, input_path: Path, base_output_dir: Path, verbose: bool = False,
            sqlite_db_path: Path | None = None) -> ExtractionContext:
        run_dir = make_run_output_dir(base_output_dir)
        setup_logging(run_dir / "error_log.txt", verbose=verbose)
        try:
            return self._run_pipeline(input_path, run_dir, sqlite_db_path)
        finally:
            # Always release the log file's OS-level handle before returning,
            # regardless of which exit path was taken (success, read failure,
            # or an unexpected exception). Without this, Windows will refuse
            # to delete/rename run_dir afterward (e.g. temp-directory cleanup
            # in tests) because the file handle is still open.
            close_logging()

    def _run_pipeline(self, input_path: Path, run_dir: Path,
                       sqlite_db_path: Path | None = None) -> ExtractionContext:
        start_time = time.time()
        logger.info("Starting extraction run for '%s' -> output dir '%s'", input_path, run_dir)

        ctx = ExtractionContext(input_path=str(input_path), output_dir=str(run_dir))

        reader = ExcelReaderAgent(
            sparse_row_threshold=self.config["sparse_row_threshold"],
            max_file_size_mb=self.config.get("max_file_size_mb", 100),
            detect_formulas=self.config.get("detect_formulas", True),
            max_rows_per_sheet=self.config.get("max_rows_per_sheet", 100000),
        )
        mapper = SchemaMapperAgent(
            threshold=self.config["fuzzy_match_threshold"],
            enable_local_llm=self.config["enable_local_llm"],
            llm_model=self.config["llm_model"],
        )
        cleaner = DataCleaningAgent(date_locale=self.config.get("date_locale", "us"))
        extractor = RecordExtractionAgent()
        validator = ValidationAgent(duplicate_key_fields=self.config["duplicate_key_fields"])
        formatter = OutputFormatterAgent()

        try:
            profiles, grids = reader.read_workbook(input_path)
        except Exception as exc:
            logger.exception("Failed to read workbook '%s'", input_path)
            ctx.add_issue(IssueSeverity.ERROR, "<workbook>", f"Failed to open workbook: {exc}")
            formatter.write_all(ctx, run_dir)
            return ctx

        ctx.sheet_profiles = profiles
        total_sheets = len(profiles)
        sheets_processed = 0

        # Step check: read
        elapsed = time.time() - start_time
        if elapsed > self.max_processing_time:
            step = "read"
            logger.warning(
                "Processing time exceeded %ss after %s. Returning partial results.",
                self.max_processing_time, step
            )
            ctx.add_issue(
                IssueSeverity.ERROR,
                "<workbook>",
                f"Pipeline timed out after {elapsed:.1f}s. {sheets_processed} of {total_sheets} sheets were processed.",
            )
            ctx.timed_out = True
            formatter.write_all(ctx, run_dir)
            return ctx

        successful_sheets = 0

        for sheet_name, profile in profiles.items():
            grid = grids[sheet_name]

            if profile.is_sparse and profile.n_rows < 2:
                ctx.add_issue(IssueSeverity.WARNING, sheet_name,
                               "Sheet appears empty or near-empty; skipping.")
                logger.warning("Skipping sheet '%s' -- effectively empty.", sheet_name)
                sheets_processed += 1
                successful_sheets += 1
                continue

            if profile.is_sparse:
                threshold_pct = int(self.config.get("sparse_row_threshold", 0.9) * 100)
                hdr_idx = profile.header_row_index if profile.header_row_index is not None else 0
                ctx.add_issue(
                    IssueSeverity.WARNING,
                    sheet_name,
                    f"Sheet '{sheet_name}' is flagged as sparse (>{threshold_pct}% empty cells). "
                    f"The data may be scattered across a wide range. Verify that the header row "
                    f"was detected correctly (detected at row {hdr_idx}).",
                )

            try:
                header_row = (
                    grid[profile.header_row_index]
                    if profile.header_row_index is not None and profile.header_row_index < len(grid)
                    else []
                )
                headers = [
                    (str(h).strip() if h is not None and str(h).strip() != "" else f"column_{i+1}")
                    for i, h in enumerate(header_row)
                ]
                # Guard against duplicate raw header names within one sheet.
                headers = self._dedupe_headers(headers, sheet_name, ctx)

                schema_map = mapper.map_headers(headers)
                ctx.schema_maps[sheet_name] = schema_map

                clean_rows = cleaner.clean_sheet(grid, profile.header_row_index, headers,
                                                  schema_map, sheet_name, ctx)

                records = extractor.extract_records(clean_rows, schema_map, sheet_name, ctx)
                ctx.records.extend(records)

                hdr_offset = profile.header_row_index if profile.header_row_index is not None else 0
                raw_row_count = len(grid) - hdr_offset - 1
                report = validator.validate(sheet_name, raw_row_count, records, schema_map, ctx)
                ctx.validation_reports.append(report)

                successful_sheets += 1
            except Exception as exc:
                logger.exception("Failed to process sheet '%s'", sheet_name)
                ctx.add_issue(
                    IssueSeverity.ERROR,
                    sheet_name,
                    f"Sheet '{sheet_name}' failed during processing: {exc}. Skipping this sheet.",
                )
                sheets_processed += 1
                continue

            sheets_processed += 1

            # Step check: per-sheet clean/map/extract/validate
            elapsed = time.time() - start_time
            if elapsed > self.max_processing_time:
                step = "per-sheet clean/map/extract/validate"
                logger.warning(
                    "Processing time exceeded %ss after %s. Returning partial results.",
                    self.max_processing_time, step
                )
                ctx.add_issue(
                    IssueSeverity.ERROR,
                    "<workbook>",
                    f"Pipeline timed out after {elapsed:.1f}s. {sheets_processed} of {total_sheets} sheets were processed.",
                )
                ctx.timed_out = True
                break

        logger.info("Processed %d/%d sheets successfully.", successful_sheets, total_sheets)

        for sheet_name, schema_map in ctx.schema_maps.items():
            for raw_header, mapping in schema_map.items():
                if mapping.canonical_field:
                    ctx.column_alignment.setdefault(mapping.canonical_field, {})[sheet_name] = raw_header

        if not ctx.timed_out and self.config.get("cross_sheet_dedup", True):
            deduplicator = SheetDeduplicatorAgent(
                threshold=self.config.get("cross_sheet_overlap_threshold", 0.8),
                duplicate_key_fields=self.config.get("duplicate_key_fields", None),
            )
            deduplicator.deduplicate(ctx)

        if not ctx.timed_out:
            cross_dup_count, cross_dups = validator.find_cross_sheet_duplicates(ctx.records)
            ctx.cross_sheet_duplicates = cross_dups
            if cross_dup_count:
                logger.info("Found %d cross-sheet duplicate pair(s).", cross_dup_count)
                for ref1, ref2 in cross_dups:
                    ctx.add_issue(
                        IssueSeverity.WARNING,
                        "<cross-sheet>",
                        f"Cross-sheet duplicate record found: {ref1} matches {ref2}.",
                    )

        profiler = DataProfilerAgent()
        profiler.profile(ctx)

        formatter.write_all(ctx, run_dir)

        # Step check: format
        elapsed = time.time() - start_time
        if elapsed > self.max_processing_time and not ctx.timed_out:
            step = "format"
            logger.warning(
                "Processing time exceeded %ss after %s. Returning partial results.",
                self.max_processing_time, step
            )
            ctx.add_issue(
                IssueSeverity.ERROR,
                "<workbook>",
                f"Pipeline timed out after {elapsed:.1f}s. {sheets_processed} of {total_sheets} sheets were processed.",
            )
            ctx.timed_out = True

        if sqlite_db_path is not None:
            sqlite_writer = SQLiteWriterAgent()
            sqlite_writer.write(ctx, sqlite_db_path)
            logger.info("Also persisted records to SQLite database: %s", sqlite_db_path)

        logger.info("Extraction run complete. %d total records across %d sheets.",
                     len(ctx.records), len(ctx.validation_reports))
        return ctx

    @staticmethod
    def _dedupe_headers(headers: list[str], sheet_name: str, ctx: ExtractionContext) -> list[str]:
        seen: dict[str, int] = {}
        result = []
        for h in headers:
            if h not in seen:
                seen[h] = 0
                result.append(h)
            else:
                seen[h] += 1
                new_name = f"{h}_{seen[h]+1}"
                result.append(new_name)
                ctx.add_issue(
                    IssueSeverity.WARNING,
                    sheet_name,
                    f"Duplicate header '{h}' renamed to '{new_name}' to avoid collision. "
                    "Check if this column should be merged with the original.",
                    column=new_name,
                )
        return result
