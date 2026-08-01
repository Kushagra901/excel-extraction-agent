# Excel Extraction Agent

A free, local-first, deterministic-first pipeline that takes a messy real-world
`.xlsx` workbook and turns it into structured, traceable, machine-readable
output — CSV, JSON, a schema map, and a human-readable Markdown report.

No paid APIs. No cloud services required. Everything runs on your machine.

---

## Why this exists

Real spreadsheets lie about their own structure: merged header cells, blank
separator rows, repeated headers mid-sheet, mixed date formats, currency
symbols, placeholder nulls (`N/A`, `TBD`, `-`). This project handles that mess
with **rule-based, deterministic logic first**, and only ever guesses when it
tells you it's guessing — every mapped field carries a confidence score, every
dropped row is logged with a reason, and every output record can be traced
back to its exact source sheet and row number.

## Architecture at a glance

```
.xlsx file
    │
    ▼
Excel Reader Agent    → detects sheets, header rows, merged cells, hidden rows/cols
    ▼
Schema Mapping Agent  → maps messy headers to canonical fields (exact → fuzzy → optional local LLM)
    ▼
Data Cleaning Agent   → normalizes dates, numbers, emails, phones; drops blank/repeated rows (logged)
    ▼
Record Extraction Agent → produces canonical records, traceable to source sheet + row
    ▼
Validation & QA Agent → row-count reconciliation, duplicate detection, suspicious-value flags
    ▼
Output Formatter Agent → cleaned_data.csv, extracted_data.json, schema_map.json,
                          extraction_report.md, error_log.txt
```

Each stage is a real Python module with a defined input/output contract
(`src/core/models.py`) — not a black box. See `src/orchestrator.py` for the
full pipeline wiring.

---

## Installation

Requires **Python 3.11+**.

```bash
git clone <this-repo>   # or unzip the project folder
cd excel-extraction-agent

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
# If your Python is "externally managed" (common on newer Linux distros):
pip install -r requirements.txt --break-system-packages
```

Verify the install:

```bash
pip install pytest
pytest tests/ -v
# Expect: 20 passed
```

---

## Usage

```bash
# Basic run — output goes to output/<timestamp>_run/
python cli.py path/to/your_file.xlsx

# Custom output location
python cli.py path/to/your_file.xlsx --output-dir my_results

# Verbose console logging (DEBUG level)
python cli.py path/to/your_file.xlsx --verbose

# Custom thresholds/config
python cli.py path/to/your_file.xlsx --config my_config.yaml

# Optional: use a local LLM (Ollama) for headers that fuzzy matching can't
# confidently map. Requires Ollama installed and running (see below).
python cli.py path/to/your_file.xlsx --enable-local-llm
```

### What you get back

In `output/<timestamp>_run/`:

| File | Purpose |
|---|---|
| `cleaned_data.csv` | Flat table, one row per record, union of all canonical fields — open in Excel/LibreOffice for a quick look |
| `extracted_data.json` | Full structured records with `_source_sheet` / `_source_row` traceability |
| `schema_map.json` | Exactly how every raw header was interpreted, with a confidence score and method (`exact` / `fuzzy` / `llm` / `unmapped`) |
| `extraction_report.md` | Human-readable summary: row counts, drop reasons, duplicates, confidence table |
| `error_log.txt` | Full chronological list of every warning/info/error, one per line |

### How to check it actually worked (manual review — do this every time on a new file format)

1. Run `pytest tests/ -v` once after any code change — should say `20 passed`.
2. Open `extraction_report.md`. For every sheet, `raw_row_count` should equal
   `extracted_record_count + dropped_row_count`. If it doesn't, something is
   being lost silently — that shouldn't happen, and is worth investigating.
3. Check the confidence table — anything below ~0.85 (flagged with ⚠️) was a
   fuzzy or LLM guess. Confirm it mapped to the right field.
4. Check `dropped_reasons` — if a sheet dropped far more rows than expected,
   trace the row numbers back to the original file via `error_log.txt`.
5. Check `duplicate_row_refs` — open the original file at those exact rows
   and confirm they're real duplicates.
6. Scan `error_log.txt` for `ERROR` severity — a clean run should have zero.
7. Spot-check 3–5 records in `extracted_data.json` against the original file
   by eye, using `_source_row`.

---

## Configuration (`config.yaml`)

```yaml
fuzzy_match_threshold: 0.72     # minimum similarity (0-1) to map a header without exact match
sparse_row_threshold: 0.9       # sheet flagged "sparse" if this fraction of cells are empty
duplicate_key_fields:           # first available field on a record is used as the dedup key
  - email
  - id
  - full_name
enable_local_llm: false
llm_model: "llama3.1"
```

---

## Optional: local LLM assist (Ollama)

Only used as a **last resort**, when a header fails both exact and fuzzy
matching. Fully local — no data leaves your machine, no API key.

1. Install [Ollama](https://ollama.com) (free, desktop app).
2. `ollama pull llama3.1`
3. `ollama serve` (leave running in the background)
4. Run with `--enable-local-llm`

If Ollama isn't running, the header simply stays unmapped — the pipeline
never crashes because of this, and never silently treats an LLM guess as
more trustworthy than a fuzzy match (both get flagged for manual review).

**Trade-off**: turning this on means identical input can occasionally produce
slightly different output between runs (since a language model's guess isn't
guaranteed deterministic), and it requires a separate background process.
For most spreadsheets, adding synonyms directly to
`src/core/canonical_schema.py` is faster and stays fully deterministic —
reach for the LLM only if you're hitting a constant stream of genuinely novel
header text that hand-editing can't keep up with.

---

## Optional: SQLite storage

Persist extracted records into a local SQLite database (stdlib `sqlite3`,
no server, no extra install) instead of — or in addition to — the per-run
CSV/JSON files. Useful for accumulating records across multiple files/runs
into one queryable place.

```bash
python cli.py path/to/your_file.xlsx --sqlite-db extracted.db
```

Each canonical field (`full_name`, `email`, `amount`, etc.) becomes a real,
queryable column; any raw headers that never mapped to a canonical field are
preserved in an `extra_fields` JSON column so nothing is lost. Every row is
tagged with `source_file`, `source_sheet`, and `source_row` for traceability,
and running against the same `--sqlite-db` path multiple times **appends**
rather than overwrites — so you can build up a history across many files.

```bash
sqlite3 extracted.db "SELECT full_name, email, amount FROM records WHERE amount > 1000;"
```

## Optional: Streamlit UI

A drag-and-drop web UI for the same pipeline — upload a file, see the
report/data/schema/errors in tabs, download the outputs. Nothing leaves your
machine; it's the identical `Supervisor` pipeline the CLI uses, just with a
browser front end instead of a terminal.

```bash
pip install -r requirements-ui.txt
streamlit run app.py
```

This is intentionally a separate requirements file — the core CLI pipeline
does not need Streamlit installed to run.

---

## Extending the system

| Want to... | Touch this file |
|---|---|
| Recognize a new field type or header phrasing | `src/core/canonical_schema.py` |
| Add a new cleaning rule (postal codes, URLs, etc.) | `src/core/cleaning_rules.py` — follow the `(value) -> (cleaned, valid, note)` contract |
| Change fuzzy-matching aggressiveness | `config.yaml` → `fuzzy_match_threshold` |
| Add a new output format | New method on `OutputFormatterAgent` in `src/agents/output_formatter.py` |
| Support `.xls` or `.csv` input | New reader agent producing the same `(SheetProfile, grid)` shape as `excel_reader.py` |
| Persist to a database | `src/agents/sqlite_writer.py` — writes records into a local SQLite file, no server needed (already wired to `--sqlite-db`) |
| Add a UI | `app.py` — a Streamlit front end that wraps the `Supervisor` directly (already built, `streamlit run app.py`) |
| Dedupe across sheets, not just within one | Extend `ValidationAgent._find_duplicates` to operate on the full `ctx.records` list |

The rule of thumb: "teach it about new data" belongs in `canonical_schema.py`
or `cleaning_rules.py`; "change pipeline behavior" is one agent file. You
should rarely need to touch more than one or two files for any extension.

---

## Known limitations

- **Header detection is heuristic**, scored on the first 15 rows of a sheet.
  Unusual layouts (headers split across two rows, vertically-oriented
  tables) may be mis-detected — check `header_row_index` in the logs for a
  genuinely new file format.
- **Duplicate detection is per-sheet**, not global across the whole workbook.
- **`cleaned_data.csv` is a union of fields across all sheets** — a workbook
  with structurally very different sheets will produce a wide, sparse CSV.
  Prefer `extracted_data.json` for downstream processing in that case.
- **Fuzzy matching is character-level, not semantic** — it has no real
  understanding of meaning, only string similarity. Always check the
  confidence table for anything below ~0.85.
- **Date parsing tries U.S. format (`MM/DD/YYYY`) before international
  (`DD/MM/YYYY`)** for ambiguous dates. If your source data isn't
  U.S.-formatted, reorder `_DATE_FORMATS` in `src/core/cleaning_rules.py`
  before trusting date output.
- **No streaming/chunking** — the whole workbook loads into memory. Fine for
  typical business spreadsheets; large files (500k+ rows) would need
  `pandas.read_excel` chunking, not currently implemented.
- **Not a substitute for reading the report.** This system is built to make
  its own uncertainty visible (confidence scores, drop reasons, issue logs)
  — it is not built to be trusted blindly. Treat a first run on any new
  spreadsheet format as "verify before you rely on it."

## Running the tests

```bash
pytest tests/ -v
```

23 tests covering: cleaning-rule edge cases (dates, currency, emails,
phones), header/merged-cell/sparsity detection, schema mapping (including a
regression test for a real fuzzy-matching bug), full pipeline integration
(including regression tests for real bugs found during development: silent
row-drop undercounting, dropped-reason miscategorization, and a Windows
file-handle leak), and the optional SQLite writer (table creation, opt-in
behavior, multi-run accumulation).
