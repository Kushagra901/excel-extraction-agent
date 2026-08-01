"""
SQLite Writer Agent (optional advanced feature).

Persists extracted records into a local SQLite database file -- no server,
no separate install, uses only Python's stdlib `sqlite3`. This is useful if
you want to accumulate records across multiple runs/files into one queryable
place, rather than just getting a fresh CSV/JSON per run.

Schema design:
  - One wide `records` table with a column per CANONICAL field (kept in
    sync automatically -- add a field to canonical_schema.py and it shows
    up here too, no manual migration needed).
  - Any raw headers that never mapped to a canonical field are preserved in
    an `extra_fields` JSON column, so nothing is lost even though the table
    itself only has fixed canonical columns.
  - Each row is tagged with source_file / source_sheet / source_row /
    imported_at, so records from multiple runs/files can coexist in the
    same database without collisions, and every row is still traceable
    back to its origin.

This module is entirely optional -- the core pipeline works with or without
it, and nothing else in the codebase depends on it.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
from pathlib import Path

from src.core.canonical_schema import CANONICAL_SCHEMA
from src.core.models import ExtractionContext

logger = logging.getLogger("excel_agent.sqlite_writer")

_CANONICAL_FIELDS = list(CANONICAL_SCHEMA.keys())

# amount/quantity are numeric; everything else canonical is stored as TEXT
# (dates as ISO strings, ids/names/etc. as plain text).
_NUMERIC_FIELDS = {"amount", "quantity"}


class SQLiteWriterAgent:
    def write(self, ctx: ExtractionContext, db_path: Path) -> int:
        """Writes all records in ctx to db_path, creating the table if it
        doesn't exist yet. Returns the number of rows written."""
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(db_path)
        try:
            self._ensure_schema(conn)
            written = self._insert_records(conn, ctx)
            conn.commit()
        finally:
            conn.close()

        logger.info("Wrote %d record(s) to SQLite database '%s'.", written, db_path)
        return written

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        columns = ["record_id INTEGER PRIMARY KEY AUTOINCREMENT",
                   "source_file TEXT", "source_sheet TEXT", "source_row INTEGER"]
        for field in _CANONICAL_FIELDS:
            col_type = "REAL" if field in _NUMERIC_FIELDS else "TEXT"
            columns.append(f'"{field}" {col_type}')
        columns += ["extra_fields TEXT", "issues TEXT", "imported_at TEXT"]

        conn.execute(f"CREATE TABLE IF NOT EXISTS records ({', '.join(columns)})")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_records_source "
            "ON records (source_file, source_sheet, source_row)"
        )

    @staticmethod
    def _insert_records(conn: sqlite3.Connection, ctx: ExtractionContext) -> int:
        now = dt.datetime.now().isoformat(timespec="seconds")
        insert_cols = ["source_file", "source_sheet", "source_row"] + _CANONICAL_FIELDS + \
                      ["extra_fields", "issues", "imported_at"]
        placeholders = ", ".join("?" for _ in insert_cols)
        col_list = ", ".join(f'"{c}"' for c in insert_cols)
        sql = f"INSERT INTO records ({col_list}) VALUES ({placeholders})"

        rows = []
        for record in ctx.records:
            canonical_values = [record.data.get(field) for field in _CANONICAL_FIELDS]
            extra = {k: v for k, v in record.data.items() if k not in CANONICAL_SCHEMA}
            rows.append((
                ctx.input_path, record.source_sheet, record.source_row,
                *canonical_values,
                json.dumps(extra) if extra else None,
                json.dumps(record.record_issues) if record.record_issues else None,
                now,
            ))

        conn.executemany(sql, rows)
        return len(rows)
