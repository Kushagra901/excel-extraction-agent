import tempfile
from pathlib import Path

from src.orchestrator import Supervisor
from src.utils.file_helpers import DEFAULT_CONFIG

FIXTURE = Path(__file__).parent / "fixtures" / "messy_sample.xlsx"


def test_timeout_protection_triggers_and_returns_partial_results():
    with tempfile.TemporaryDirectory() as tmp:
        config = dict(DEFAULT_CONFIG)
        # Setting max_processing_time_seconds to -1 forces immediate timeout
        config["max_processing_time_seconds"] = -1

        supervisor = Supervisor(config=config)
        ctx = supervisor.run(FIXTURE, Path(tmp))

        assert ctx.timed_out is True
        # Check that error issue was recorded
        timeout_issues = [
            i for i in ctx.issues
            if "timed out after" in i.message and i.severity.value == "error"
        ]
        assert len(timeout_issues) == 1
        assert "sheets were processed" in timeout_issues[0].message

        # Output files should still be created with partial results
        run_dir = Path(ctx.output_dir)
        for filename in ("cleaned_data.csv", "extracted_data.json", "schema_map.json",
                          "extraction_report.md", "error_log.txt"):
            assert (run_dir / filename).exists(), f"missing output file: {filename}"


def test_timeout_config_default_present():
    assert "max_processing_time_seconds" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["max_processing_time_seconds"] == 300
