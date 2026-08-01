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

from src.orchestrator import Supervisor
from src.utils.file_helpers import DEFAULT_CONFIG

st.set_page_config(page_title="Excel Extraction Agent", page_icon="📊", layout="wide")

st.title("📊 Excel Extraction Agent")
st.caption(
    "Free, local-first extraction for messy Excel workbooks. "
    "Nothing you upload here leaves this machine."
)

with st.sidebar:
    st.header("Settings")
    fuzzy_threshold = st.slider(
        "Fuzzy match threshold", min_value=0.5, max_value=1.0,
        value=float(DEFAULT_CONFIG["fuzzy_match_threshold"]), step=0.01,
        help="Minimum similarity score for a header to be mapped to a "
             "canonical field without an exact match. Lower = more "
             "aggressive mapping, higher = more headers left unmapped "
             "for manual review.",
    )
    enable_llm = st.checkbox(
        "Enable local LLM assist", value=False,
        help="Requires Ollama running locally (localhost:11434). If it "
             "isn't running, ambiguous headers simply stay unmapped -- "
             "this checkbox will not cause a crash either way.",
    )
    st.divider()
    st.markdown(
        "**How to check the result is trustworthy:**\n"
        "1. Open the Report tab -- raw rows should equal extracted + dropped.\n"
        "2. Check the Schema Map tab for any confidence below ~0.85.\n"
        "3. Scan the Error Log tab for any `ERROR` severity lines."
    )

uploaded = st.file_uploader("Upload an .xlsx file", type=["xlsx"])

if uploaded is None:
    st.info("Upload an .xlsx file to get started.")
    st.stop()

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    input_path = tmp_path / uploaded.name
    input_path.write_bytes(uploaded.getvalue())

    config = dict(DEFAULT_CONFIG)
    config["fuzzy_match_threshold"] = fuzzy_threshold
    config["enable_local_llm"] = enable_llm

    with st.spinner("Extracting..."):
        supervisor = Supervisor(config=config)
        ctx = supervisor.run(input_path, tmp_path / "output", verbose=False)

    run_dir = Path(ctx.output_dir)

    error_count = sum(1 for i in ctx.issues if i.severity.value == "error")
    if error_count:
        st.error(f"Extraction finished with {error_count} error(s) -- check the Error Log tab.")
    else:
        st.success(
            f"Extracted {len(ctx.records)} record(s) from "
            f"{len(ctx.sheet_profiles)} sheet(s)."
        )

    tab_report, tab_data, tab_schema, tab_errors = st.tabs(
        ["📋 Report", "📄 Cleaned Data", "🗺️ Schema Map", "⚠️ Error Log"]
    )

    with tab_report:
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
