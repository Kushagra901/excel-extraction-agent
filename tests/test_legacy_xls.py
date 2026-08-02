import tempfile
from pathlib import Path

import pytest

from src.agents.excel_reader import ExcelReaderAgent
from src.orchestrator import Supervisor
from src.utils.file_helpers import DEFAULT_CONFIG

LEGACY_FIXTURE = Path(__file__).parent / "fixtures" / "sample_legacy.xls"


def test_excel_reader_handles_legacy_xls():
    reader = ExcelReaderAgent()
    profiles, grids = reader.read_workbook(LEGACY_FIXTURE)

    assert "Sheet1" in profiles
    profile = profiles["Sheet1"]
    assert profile.n_rows == 2
    assert profile.has_formulas is False
    assert any("Legacy .xls format" in note for note in profile.notes)

    grid = grids["Sheet1"]
    assert grid[0] == ["Full Name", "Email"]
    assert grid[1] == ["Alice Smith", "alice@example.com"]


def test_full_pipeline_with_legacy_xls(tmp_path):
    supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
    out_dir = tmp_path / "output"
    ctx = supervisor.run(LEGACY_FIXTURE, out_dir)

    assert len(ctx.records) == 1
    assert ctx.records[0].data.get("full_name") == "Alice Smith"
    assert ctx.records[0].data.get("email") == "alice@example.com"

    run_dir = Path(ctx.output_dir)
    assert (run_dir / "cleaned_data.csv").exists()
    assert (run_dir / "extraction_report.md").exists()


def test_unsupported_file_extension_or_signature(tmp_path):
    pdf_file = tmp_path / "sample.pdf"
    pdf_file.write_bytes(b"%PDF-1.5 fake pdf content")

    reader = ExcelReaderAgent()
    with pytest.raises(ValueError, match="Unsupported file format"):
        reader.read_workbook(pdf_file)
