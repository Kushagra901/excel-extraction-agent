"""
Supervisor Agent (orchestrator).

Owns the end-to-end plan and runs every other agent in the correct order,
per sheet. This is the only file that knows the full pipeline shape --
every other agent only knows its own phase.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.agents.data_cleaner import DataCleaningAgent
from src.agents.excel_reader import ExcelReaderAgent
from src.agents.output_formatter import OutputFormatterAgent
from src.agents.record_extractor import RecordExtractionAgent
from src.agents.schema_mapper import SchemaMapperAgent
from src.agents.sqlite_writer import SQLiteWriterAgent
from src.agents.validator import ValidationAgent
from src.core.models import ExtractionContext, IssueSeverity
from src.utils.file_helpers import make_run_output_dir
from src.utils.logging_setup import close_logging, setup_logging

logger = logging.getLogger("excel_agent.orchestrator")


class Supervisor:
    def __init__(self, config: dict):
        self.config = config

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
        logger.info("Starting extraction run for '%s' -> output dir '%s'", input_path, run_dir)

        ctx = ExtractionContext(input_path=str(input_path), output_dir=str(run_dir))

        reader = ExcelReaderAgent(sparse_row_threshold=self.config["sparse_row_threshold"])
        mapper = SchemaMapperAgent(
            threshold=self.config["fuzzy_match_threshold"],
            enable_local_llm=self.config["enable_local_llm"],
            llm_model=self.config["llm_model"],
        )
        cleaner = DataCleaningAgent()
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

        for sheet_name, profile in profiles.items():
            grid = grids[sheet_name]

            if profile.is_sparse and profile.n_rows < 2:
                ctx.add_issue(IssueSeverity.WARNING, sheet_name,
                               "Sheet appears empty or near-empty; skipping.")
                logger.warning("Skipping sheet '%s' -- effectively empty.", sheet_name)
                continue

            header_row = grid[profile.header_row_index]
            headers = [
                (str(h).strip() if h is not None and str(h).strip() != "" else f"column_{i+1}")
                for i, h in enumerate(header_row)
            ]
            # Guard against duplicate raw header names within one sheet.
            headers = self._dedupe_headers(headers)

            schema_map = mapper.map_headers(headers)
            ctx.schema_maps[sheet_name] = schema_map

            clean_rows = cleaner.clean_sheet(grid, profile.header_row_index, headers,
                                              schema_map, sheet_name, ctx)

            records = extractor.extract_records(clean_rows, schema_map, sheet_name, ctx)
            ctx.records.extend(records)

            raw_row_count = len(grid) - profile.header_row_index - 1
            report = validator.validate(sheet_name, raw_row_count, records, schema_map, ctx)
            ctx.validation_reports.append(report)

        formatter.write_all(ctx, run_dir)

        if sqlite_db_path is not None:
            sqlite_writer = SQLiteWriterAgent()
            sqlite_writer.write(ctx, sqlite_db_path)
            logger.info("Also persisted records to SQLite database: %s", sqlite_db_path)

        logger.info("Extraction run complete. %d total records across %d sheets.",
                     len(ctx.records), len(ctx.validation_reports))
        return ctx

    @staticmethod
    def _dedupe_headers(headers: list[str]) -> list[str]:
        seen: dict[str, int] = {}
        result = []
        for h in headers:
            if h not in seen:
                seen[h] = 0
                result.append(h)
            else:
                seen[h] += 1
                result.append(f"{h}_{seen[h]+1}")
        return result
