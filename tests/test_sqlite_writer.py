import sqlite3
import tempfile
from pathlib import Path

from src.orchestrator import Supervisor
from src.utils.file_helpers import DEFAULT_CONFIG

FIXTURE = Path(__file__).parent / "fixtures" / "messy_sample.xlsx"


def test_sqlite_output_creates_table_and_rows():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "extracted.db"

        supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
        ctx = supervisor.run(FIXTURE, tmp_path, sqlite_db_path=db_path)

        assert db_path.exists()

        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute("SELECT COUNT(*) FROM records")
            row_count = cur.fetchone()[0]
            assert row_count == len(ctx.records)

            # Canonical fields should be real columns, queryable directly --
            # not buried in a JSON blob.
            cur = conn.execute(
                "SELECT full_name, email, amount FROM records WHERE full_name = ?",
                ("Alice Johnson",),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[1] == "alice.j@example.com"
            assert row[2] == 1250.0
        finally:
            conn.close()


def test_sqlite_output_is_opt_in_and_does_not_break_normal_run():
    """Regression-style test: running WITHOUT sqlite_db_path must behave
    identically to before this feature existed -- no db file, no crash."""
    with tempfile.TemporaryDirectory() as tmp:
        supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
        ctx = supervisor.run(FIXTURE, Path(tmp))
        assert len(ctx.records) == 11
        assert not (Path(tmp) / "extracted.db").exists()


def test_sqlite_output_accumulates_across_multiple_runs():
    """Two separate runs against the same db file should both land in the
    same table, distinguishable by source_file -- this is the main point
    of offering SQLite output instead of just per-run CSV/JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "extracted.db"

        supervisor = Supervisor(config=dict(DEFAULT_CONFIG))
        supervisor.run(FIXTURE, tmp_path, sqlite_db_path=db_path)
        supervisor.run(FIXTURE, tmp_path, sqlite_db_path=db_path)

        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute("SELECT COUNT(*) FROM records")
            assert cur.fetchone()[0] == 22  # 11 records x 2 runs
        finally:
            conn.close()
