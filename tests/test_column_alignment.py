import tempfile
from pathlib import Path

import openpyxl

from src.orchestrator import Supervisor
from src.utils.file_helpers import DEFAULT_CONFIG


def test_cross_sheet_column_alignment_computation(tmp_path):
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Sheet1"
    ws1.append(["Customer Name", "Email", "Total"])
    ws1.append(["Alice Smith", "alice@example.com", "100.0"])

    ws2 = wb.create_sheet(title="Sheet2")
    ws2.append(["Client", "E-Mail Addr", "Amount Due"])
    ws2.append(["Bob Jones", "bob@example.com", "150.0"])

    excel_path = tmp_path / "diff_headers.xlsx"
    wb.save(excel_path)

    out_dir = tmp_path / "output"
    supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
    ctx = supervisor.run(excel_path, out_dir)

    # Check ctx.column_alignment mapping
    alignment = ctx.column_alignment
    assert "full_name" in alignment
    assert alignment["full_name"]["Sheet1"] == "Customer Name"
    assert alignment["full_name"]["Sheet2"] == "Client"

    assert "email" in alignment
    assert alignment["email"]["Sheet1"] == "Email"
    assert alignment["email"]["Sheet2"] == "E-Mail Addr"

    assert "amount" in alignment
    assert alignment["amount"]["Sheet1"] == "Total"
    assert alignment["amount"]["Sheet2"] == "Amount Due"

    # Check report section
    run_dir = Path(ctx.output_dir)
    report_text = (run_dir / "extraction_report.md").read_text(encoding="utf-8")
    assert "Cross-Sheet Column Alignment" in report_text
    assert "Customer Name" in report_text
    assert "Client" in report_text
