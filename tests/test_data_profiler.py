import tempfile
from pathlib import Path

from src.agents.data_profiler import DataProfilerAgent
from src.core.models import ExtractionContext, Record
from src.orchestrator import Supervisor
from src.utils.file_helpers import DEFAULT_CONFIG


def test_data_profiler_agent_numeric_string_dates():
    records = [
        Record(source_sheet="Sheet1", source_row=2, data={"full_name": "Alice", "amount": 10.0, "created_at": "2026-01-01"}),
        Record(source_sheet="Sheet1", source_row=3, data={"full_name": "Bob", "amount": 50.0, "created_at": "2026-01-15"}),
        Record(source_sheet="Sheet1", source_row=4, data={"full_name": "Alice", "amount": 90.0, "created_at": "2026-02-01"}),
        Record(source_sheet="Sheet1", source_row=5, data={"full_name": None, "amount": None, "created_at": None}),
    ]

    ctx = ExtractionContext(input_path="test.xlsx", output_dir="out")
    ctx.records = records

    profiler = DataProfilerAgent()
    profiler.profile(ctx)

    assert len(ctx.column_profiles) == 3
    prof_dict = {cp.field_name: cp for cp in ctx.column_profiles}

    # full_name profiling
    fn_prof = prof_dict["full_name"]
    assert fn_prof.total_count == 4
    assert fn_prof.null_count == 1
    assert fn_prof.null_percentage == 25.0
    assert fn_prof.unique_count == 2
    assert fn_prof.top_values[0] == ("Alice", 2)
    assert fn_prof.quality_score == 87.5

    # amount profiling
    amt_prof = prof_dict["amount"]
    assert amt_prof.min_value == 10.0
    assert amt_prof.max_value == 90.0
    assert amt_prof.mean_value == 50.0

    # created_at profiling
    dt_prof = prof_dict["created_at"]
    assert dt_prof.min_date == "2026-01-01"
    assert dt_prof.max_date == "2026-02-01"


def test_full_pipeline_data_profiler_integration(tmp_path):
    csv_file = tmp_path / "sales.csv"
    csv_file.write_text(
        "Full Name,Amount,Order Date\n"
        "Alice Smith,100.50,2026-03-01\n"
        "Bob Jones,250.00,2026-03-10\n"
        "Charlie Brown,,2026-03-15\n",
        encoding="utf-8",
    )

    supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
    out_dir = tmp_path / "output"
    ctx = supervisor.run(csv_file, out_dir)

    assert len(ctx.column_profiles) == 3
    report_text = (Path(ctx.output_dir) / "extraction_report.md").read_text(encoding="utf-8")
    assert "Data Profile" in report_text
    assert "Overall Data Quality Score" in report_text
