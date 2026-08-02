import tempfile
from pathlib import Path

import pytest

from src.agents.excel_reader import ExcelReaderAgent
from src.orchestrator import Supervisor
from src.utils.file_helpers import DEFAULT_CONFIG


def test_csv_comma_separated_utf8(tmp_path):
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("Full Name,Email\nAlice Smith,alice@example.com\nBob Jones,bob@example.com", encoding="utf-8")

    reader = ExcelReaderAgent()
    profiles, grids = reader.read_workbook(csv_file)

    assert "csv_data" in profiles
    profile = profiles["csv_data"]
    assert profile.n_rows == 3
    assert profile.has_formulas is False
    assert any("CSV import — delimiter: ','" in note for note in profile.notes)

    grid = grids["csv_data"]
    assert grid[0] == ["Full Name", "Email"]
    assert grid[1] == ["Alice Smith", "alice@example.com"]


def test_csv_semicolon_separated(tmp_path):
    csv_file = tmp_path / "data_european.csv"
    csv_file.write_text("Full Name;Email;Amount\nAlice Smith;alice@example.com;100,50\nBob Jones;bob@example.com;200,00", encoding="utf-8")

    reader = ExcelReaderAgent()
    profiles, grids = reader.read_workbook(csv_file)

    assert "csv_data" in profiles
    profile = profiles["csv_data"]
    assert any("delimiter: ';'" in note for note in profile.notes)

    grid = grids["csv_data"]
    assert grid[0] == ["Full Name", "Email", "Amount"]
    assert grid[1] == ["Alice Smith", "alice@example.com", "100,50"]


def test_tsv_tab_separated(tmp_path):
    tsv_file = tmp_path / "data.tsv"
    tsv_file.write_text("Full Name\tEmail\nAlice Smith\talice@example.com\nBob Jones\tbob@example.com", encoding="utf-8")

    reader = ExcelReaderAgent()
    profiles, grids = reader.read_workbook(tsv_file)

    assert "csv_data" in profiles
    profile = profiles["csv_data"]
    assert any("delimiter: 'TAB'" in note for note in profile.notes)

    grid = grids["csv_data"]
    assert grid[0] == ["Full Name", "Email"]
    assert grid[1] == ["Alice Smith", "alice@example.com"]


def test_csv_latin1_encoding(tmp_path):
    csv_file = tmp_path / "data_latin1.csv"
    content = "Full Name,Email,City\nFrançois Dupont,francois@example.com,Montréal\n"
    csv_file.write_bytes(content.encode("iso-8859-1"))

    reader = ExcelReaderAgent()
    profiles, grids = reader.read_workbook(csv_file)

    assert "csv_data" in profiles
    grid = grids["csv_data"]
    assert grid[1][0] == "François Dupont"
    assert grid[1][2] == "Montréal"


def test_full_pipeline_with_csv(tmp_path):
    csv_file = tmp_path / "customers.csv"
    csv_file.write_text("Full Name,Email\nAlice Smith,alice@example.com\nBob Jones,bob@example.com", encoding="utf-8")

    supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
    out_dir = tmp_path / "output"
    ctx = supervisor.run(csv_file, out_dir)

    assert len(ctx.records) == 2
    assert ctx.records[0].data.get("full_name") == "Alice Smith"
    assert ctx.records[1].data.get("email") == "bob@example.com"

    run_dir = Path(ctx.output_dir)
    assert (run_dir / "cleaned_data.csv").exists()
    assert (run_dir / "extraction_report.md").exists()
