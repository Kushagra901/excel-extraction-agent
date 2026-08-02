import tempfile
from pathlib import Path

import openpyxl

from src.agents.excel_reader import ExcelReaderAgent
from src.orchestrator import Supervisor
from src.utils.file_helpers import DEFAULT_CONFIG


def test_max_rows_per_sheet_truncates_grid_and_records(tmp_path):
    # Create a workbook with 1 header row + 20 data rows (21 rows total)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "LargeSheet"
    ws.append(["Full Name", "Email"])
    for i in range(1, 21):
        ws.append([f"User {i}", f"user{i}@example.com"])

    excel_path = tmp_path / "twenty_rows.xlsx"
    wb.save(excel_path)

    # Set max_rows_per_sheet limit to 11 (1 header + 10 data rows)
    config = dict(DEFAULT_CONFIG)
    config["max_rows_per_sheet"] = 11

    reader = ExcelReaderAgent(max_rows_per_sheet=11)
    profiles, grids = reader.read_workbook(excel_path)

    assert profiles["LargeSheet"].n_rows == 11
    assert len(grids["LargeSheet"]) == 11
    assert any("truncated to 11" in note for note in profiles["LargeSheet"].notes)

    # Run full supervisor pipeline and verify exactly 10 data records are processed
    out_dir = tmp_path / "output"
    supervisor = Supervisor(config=config)
    ctx = supervisor.run(excel_path, out_dir)

    assert len(ctx.records) == 10
    run_dir = Path(ctx.output_dir)
    report_text = (run_dir / "extraction_report.md").read_text(encoding="utf-8")
    assert "Truncated Sheet Warning" in report_text
    assert "truncated to 11" in report_text
