"""
Optional Streamlit UI for the Excel Extraction Agent (advanced/optional layer).

This is a thin wrapper around the exact same `Supervisor` pipeline used by
`cli.py` -- it does not duplicate any extraction logic. Uploading a file
here runs the identical Excel Reader -> Schema Mapper -> Data Cleaner ->
Record Extractor -> Validator -> Output Formatter pipeline, then displays
the same five output files the CLI produces, plus lets you download them.

Requires the `streamlit` package, which is NOT in the core requirements.txt
on purpose (the deterministic pipeline should not require a UI framework to
run in a script/CI context). Install separately:

    pip install streamlit

Run with:

    streamlit run app.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from src.core.canonical_schema import CANONICAL_SCHEMA
from src.orchestrator import Supervisor
from src.utils.file_helpers import DEFAULT_CONFIG

st.set_page_config(page_title="Excel Extraction Agent", page_icon="📊", layout="wide")

st.title("📊 Excel Extraction Agent")
st.caption(
    "Free, local-first extraction for messy Excel workbooks. "
    "Nothing you upload here leaves this machine."
)

if "config" not in st.session_state:
    st.session_state["config"] = dict(DEFAULT_CONFIG)

with st.sidebar:
    st.header("Settings")

    if st.button("Reset to Defaults"):
        st.session_state["config"] = dict(DEFAULT_CONFIG)
        st.rerun()

    cfg = st.session_state["config"]

    fuzzy_threshold = st.slider(
        "Fuzzy match threshold", min_value=0.5, max_value=1.0,
        value=float(cfg.get("fuzzy_match_threshold", DEFAULT_CONFIG["fuzzy_match_threshold"])),
        step=0.01,
        help="Minimum similarity score for a header to be mapped to a "
             "canonical field without an exact match.",
    )
    cfg["fuzzy_match_threshold"] = fuzzy_threshold

    enable_llm = st.checkbox(
        "Enable local LLM assist",
        value=bool(cfg.get("enable_local_llm", False)),
        help="Requires Ollama running locally (localhost:11434).",
    )
    cfg["enable_local_llm"] = enable_llm

    with st.expander("Advanced Settings"):
        sparse_threshold = st.slider(
            "Sparse sheet threshold", 0.5, 1.0,
            value=float(cfg.get("sparse_row_threshold", 0.9)),
            step=0.05,
            help="Sheets with this fraction of empty cells are flagged as sparse",
        )
        cfg["sparse_row_threshold"] = sparse_threshold

        available_fields = list(CANONICAL_SCHEMA.keys())
        default_keys = cfg.get("duplicate_key_fields", ["email", "id", "full_name"])
        valid_default_keys = [k for k in default_keys if k in available_fields]

        dup_keys = st.multiselect(
            "Dedup key fields (priority order)",
            options=available_fields,
            default=valid_default_keys,
        )
        cfg["duplicate_key_fields"] = dup_keys

        date_loc = st.radio(
            "Date format preference",
            ["US (MM/DD/YYYY)", "International (DD/MM/YYYY)"],
            index=0 if cfg.get("date_locale", "US") == "US" else 1,
        )
        cfg["date_locale"] = "US" if "US" in date_loc else "INTL"

        max_rows = st.number_input(
            "Max rows per sheet (0 = unlimited)",
            min_value=0,
            max_value=1000000,
            value=int(cfg.get("max_rows_per_sheet", 100000)),
        )
        cfg["max_rows_per_sheet"] = max_rows

    st.divider()
    st.markdown(
        "**How to check the result is trustworthy:**\n"
        "1. Open the Report tab -- raw rows should equal extracted + dropped.\n"
        "2. Check the Schema Map tab for any confidence below ~0.85.\n"
        "3. Scan the Error Log tab for any `ERROR` severity lines."
    )

uploaded = st.file_uploader("Upload an Excel or CSV file (.xlsx, .xls, .csv, .tsv)", type=["xlsx", "xls", "csv", "tsv"])

if uploaded is None:
    st.info("Upload an .xlsx, .xls, .csv, or .tsv file to get started.")
    st.stop()

max_size_mb = DEFAULT_CONFIG.get("max_file_size_mb", 100)
file_size_mb = uploaded.size / (1024 * 1024)
if file_size_mb > max_size_mb:
    st.error(
        f"File size {file_size_mb:.1f}MB exceeds limit of {max_size_mb}MB. "
        "Reduce the file size or increase max_file_size_mb in config."
    )
    st.stop()

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    input_path = tmp_path / uploaded.name
    input_path.write_bytes(uploaded.getvalue())

    config = dict(st.session_state["config"])

    with st.spinner("Extracting..."):
        supervisor = Supervisor(config=config)
        ctx = supervisor.run(input_path, tmp_path / "output", verbose=False)

    run_dir = Path(ctx.output_dir)

    if getattr(ctx, "timed_out", False) or any("timed out" in i.message.lower() for i in ctx.issues):
        st.warning("Pipeline timed out. Displaying partial results.")

    error_count = sum(1 for i in ctx.issues if i.severity.value == "error")
    if error_count:
        st.error(f"Extraction finished with {error_count} error(s) -- check the Error Log tab.")
    else:
        st.success(
            f"Extracted {len(ctx.records)} record(s) from "
            f"{len(ctx.sheet_profiles)} sheet(s)."
        )

    tab_report, tab_data, tab_schema, tab_errors, tab_comparison, tab_profile = st.tabs(
        ["📋 Report", "📄 Cleaned Data", "🗺️ Schema Map", "⚠️ Error Log", "📊 Sheet Comparison", "📈 Data Profile"]
    )

    with tab_report:
        if getattr(ctx, "sheet_overlap_report", None):
            has_identical = any("IDENTICAL" in r.get("action_taken", "") for r in ctx.sheet_overlap_report.values())
            has_partial = any("PARTIAL_OVERLAP" in r.get("action_taken", "") for r in ctx.sheet_overlap_report.values())
            if has_identical:
                st.info("Sheet Overlap Analysis: Identical sheet(s) detected and merged into one.")
            elif has_partial:
                st.warning("Sheet Overlap Analysis: Partial overlap detected between sheets.")

        if any(p.is_sparse for p in ctx.sheet_profiles.values()):
            st.warning(
                "One or more sheets in this workbook are flagged as sparse (>90% empty cells). "
                "Please verify that header rows were detected correctly and no data was missed."
            )
        report_text = (run_dir / "extraction_report.md").read_text(encoding="utf-8")
        st.markdown(report_text)

    with tab_data:
        csv_path = run_dir / "cleaned_data.csv"
        if csv_path.stat().st_size > 0:
            df = pd.read_csv(csv_path)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No records were extracted from this file.")

    with tab_schema:
        if getattr(ctx, "column_alignment", None) and len(ctx.sheet_profiles) > 1:
            st.subheader("🌐 Cross-Sheet Column Alignment")
            sheets = sorted(list(ctx.sheet_profiles.keys()))
            alignment_rows = []
            for field_name in sorted(ctx.column_alignment.keys()):
                sheet_headers = ctx.column_alignment[field_name]
                row_dict = {"Canonical Field": field_name}
                present = 0
                for s in sheets:
                    hdr = sheet_headers.get(s, "—")
                    row_dict[s] = hdr
                    if s in sheet_headers:
                        present += 1
                row_dict["Status"] = "✅ Aligned" if present == len(sheets) else f"⚠️ Partial ({present}/{len(sheets)})"
                alignment_rows.append(row_dict)
            st.dataframe(pd.DataFrame(alignment_rows), use_container_width=True)
            st.divider()

        schema_map = json.loads((run_dir / "schema_map.json").read_text(encoding="utf-8"))
        for sheet_name, mappings in schema_map.items():
            st.subheader(sheet_name)
            rows = [
                {
                    "Raw Header": raw_header,
                    "Canonical Field": m["canonical_field"] or "— unmapped —",
                    "Confidence": m["confidence"],
                    "Method": m["method"],
                }
                for raw_header, m in mappings.items()
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

    with tab_errors:
        error_text = (run_dir / "error_log.txt").read_text(encoding="utf-8")
        st.text(error_text)

    with tab_comparison:
        if not getattr(ctx, "sheet_diffs", None):
            st.info("No sheet comparison available (requires multiple sheets with data).")
        else:
            for diff in ctx.sheet_diffs:
                st.subheader(f"Diff: {diff.sheet_a} vs {diff.sheet_b}")
                st.markdown(
                    f"- **Common records:** {diff.common_record_count}\n"
                    f"- **Only in `{diff.sheet_a}`:** {diff.only_in_a_count}\n"
                    f"- **Only in `{diff.sheet_b}`:** {diff.only_in_b_count}\n"
                    f"- **Overlap:** {diff.overlap_percentage:.1f}%"
                )
                if diff.modified_records:
                    st.markdown("**Modified Field Differences:**")
                    diff_rows = [
                        {
                            f"Row ({diff.sheet_a})": m["row_a"],
                            f"Row ({diff.sheet_b})": m["row_b"],
                            "Field": m["field"],
                            f"Value ({diff.sheet_a})": m["val_a"],
                            f"Value ({diff.sheet_b})": m["val_b"],
                        }
                        for m in diff.modified_records
                    ]
                    st.dataframe(pd.DataFrame(diff_rows), use_container_width=True)
                else:
                    st.caption("No field value differences among matched records.")

    with tab_profile:
        if not getattr(ctx, "column_profiles", None):
            st.info("No data profiling available.")
        else:
            avg_quality = sum(cp.quality_score for cp in ctx.column_profiles) / len(ctx.column_profiles)
            st.metric("Overall Data Quality Score", f"{avg_quality:.1f}%")
            prof_rows = []
            for cp in ctx.column_profiles:
                top_str = ", ".join(f"{v} ({c})" for v, c in cp.top_values[:3])
                prof_rows.append(
                    {
                        "Field": cp.field_name,
                        "Records": cp.total_count,
                        "Nulls": f"{cp.null_count} ({cp.null_percentage:.1f}%)",
                        "Unique Values": cp.unique_count,
                        "Quality Score": f"{cp.quality_score:.1f}%",
                        "Top Values": top_str,
                        "Min Value / Date": cp.min_value if cp.min_value is not None else (cp.min_date or "—"),
                        "Max Value / Date": cp.max_value if cp.max_value is not None else (cp.max_date or "—"),
                    }
                )
            st.dataframe(pd.DataFrame(prof_rows), use_container_width=True)

    st.divider()
    st.subheader("Download outputs")
    output_files = [
        "cleaned_data.csv", "extracted_data.json", "schema_map.json",
        "extraction_report.md", "error_log.txt",
    ]
    cols = st.columns(len(output_files))
    for col, filename in zip(cols, output_files):
        file_path = run_dir / filename
        col.download_button(
            label=filename, data=file_path.read_bytes(), file_name=filename,
        )
