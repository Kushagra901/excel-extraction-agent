import tempfile
from pathlib import Path

from src.orchestrator import Supervisor
from src.utils.file_helpers import DEFAULT_CONFIG

FIXTURE = Path(__file__).parent / "fixtures" / "messy_sample.xlsx"


def test_full_pipeline_runs_and_produces_expected_outputs():
    with tempfile.TemporaryDirectory() as tmp:
        supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
        ctx = supervisor.run(FIXTURE, Path(tmp))

        # Customers: 8 raw data rows -> 6 records (1 blank + 1 repeated header dropped)
        # Orders: 5 raw data rows -> 4 records (1 blank dropped)
        # Notes: sparse free-text sheet, row 0 treated as its own header;
        #        one real content cell at E20 survives as 1 record (unmapped
        #        headers, but no data silently lost)
        assert len(ctx.records) == 11

        run_dir = Path(ctx.output_dir)
        for filename in ("cleaned_data.csv", "extracted_data.json", "schema_map.json",
                          "extraction_report.md", "error_log.txt"):
            assert (run_dir / filename).exists(), f"missing output file: {filename}"

        # Cross-sheet canonical consistency: both sheets should use the same
        # canonical field names despite different raw header text.
        customers_fields = {m.canonical_field for m in ctx.schema_maps["Customers"].values()}
        orders_fields = {m.canonical_field for m in ctx.schema_maps["Orders"].values()}
        assert "full_name" in customers_fields
        assert "full_name" in orders_fields  # mapped from "Client"

        # Duplicate detection worked on both sheets.
        reports_by_sheet = {r.sheet: r for r in ctx.validation_reports}
        assert reports_by_sheet["Customers"].duplicate_count == 1
        assert reports_by_sheet["Orders"].duplicate_count == 1

        # Traceability: every record must carry its source sheet + row.
        for record in ctx.records:
            assert record.source_sheet in {"Customers", "Orders", "Notes"}
            assert record.source_row > 0


def test_dropped_reason_categorization_is_specific_not_generic():
    """Regression test: the repeated-header-row drop message says 'duplicates
    the header', but the categorizer was checking for the substring 'repeat',
    which never matched -- so every repeated-header drop silently landed in
    the vague 'other' bucket instead of 'repeated_header_row'."""
    with tempfile.TemporaryDirectory() as tmp:
        supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
        ctx = supervisor.run(FIXTURE, Path(tmp))

        customers_report = next(r for r in ctx.validation_reports if r.sheet == "Customers")
        assert customers_report.dropped_reasons.get("repeated_header_row") == 1
        assert customers_report.dropped_reasons.get("blank_or_separator_row") == 1
        assert "other" not in customers_report.dropped_reasons


def test_row_count_reconciliation_identity_holds_per_sheet():
    """Regression test: blank-row drops were originally counted in a local
    variable but never logged as a ctx.Issue, so the Validation Agent's
    dropped_reasons (derived by scanning ctx.issues) silently undercounted.
    This broke the core promise of the report: raw_row_count should always
    equal extracted_record_count + dropped_row_count for every sheet."""
    with tempfile.TemporaryDirectory() as tmp:
        supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
        ctx = supervisor.run(FIXTURE, Path(tmp))

        for report in ctx.validation_reports:
            assert report.raw_row_count == report.extracted_record_count + report.dropped_row_count, (
                f"Row count identity broken for sheet '{report.sheet}': "
                f"{report.raw_row_count} != {report.extracted_record_count} + {report.dropped_row_count}"
            )


def test_log_file_handle_released_after_run():
    """Regression test: setup_logging() used to detach handlers via
    logger.handlers.clear() without closing them first, and Supervisor.run()
    never closed its own FileHandler at all. This silently leaked open file
    descriptors on every run -- invisible on POSIX (which allows deleting an
    open file) but a hard PermissionError on Windows the moment anything
    tries to remove or overwrite that log file (e.g. temp-dir cleanup, or a
    second run writing to the same path). After a run, the logger must have
    no handlers left attached."""
    import logging as _logging

    with tempfile.TemporaryDirectory() as tmp:
        supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
        supervisor.run(FIXTURE, Path(tmp))

        agent_logger = _logging.getLogger("excel_agent")
        assert agent_logger.handlers == [], (
            f"Logger still has {len(agent_logger.handlers)} attached handler(s) "
            f"after run() returned -- the log file handle was not released."
        )


def test_cross_sheet_duplicate_detection(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Customers1"
    ws1.append(["Email", "Name"])
    ws1.append(["alice@example.com", "Alice Smith"])
    ws1.append(["bob@example.com", "Bob Jones"])

    ws2 = wb.create_sheet(title="Customers2")
    ws2.append(["Email Address", "Full Name"])
    ws2.append(["alice@example.com", "Alice S."])
    ws2.append(["charlie@example.com", "Charlie Brown"])

    excel_path = tmp_path / "multi_sheet_dups.xlsx"
    wb.save(excel_path)

    supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
    ctx = supervisor.run(excel_path, tmp_path / "output")

    assert len(ctx.cross_sheet_duplicates) == 1
    ref1, ref2 = ctx.cross_sheet_duplicates[0]
    assert "Customers1" in ref1
    assert "Customers2" in ref2

    report_text = (Path(ctx.output_dir) / "extraction_report.md").read_text(encoding="utf-8")
    assert "## Cross-Sheet Duplicates" in report_text
    assert "Customers1" in report_text and "Customers2" in report_text


def test_dedupe_headers_logs_warning_on_rename():
    from src.core.models import ExtractionContext, IssueSeverity
    ctx = ExtractionContext(input_path="test.xlsx", output_dir="output")
    headers = ["Name", "Name", "Email"]
    deduped = Supervisor._dedupe_headers(headers, "Sheet1", ctx)
    assert deduped == ["Name", "Name_2", "Email"]

    warning_issues = [
        i for i in ctx.issues
        if i.severity == IssueSeverity.WARNING
        and "Duplicate header 'Name' renamed to 'Name_2'" in i.message
    ]
    assert len(warning_issues) == 1
    assert warning_issues[0].column == "Name_2"
    assert warning_issues[0].sheet == "Sheet1"


