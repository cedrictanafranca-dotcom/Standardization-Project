r"""Step 6 — Simple UI (Streamlit).

A thin wrapper over the Step 3/4/5 pipeline in src/standardize_file.py: upload
a raw-value file, pick the field/taxonomy, hit Run, get a downloadable result.
No new classification logic lives here — this file only handles the UI and
calls into the same functions the CLI (src/standardize_file.py) already uses
and the tests already cover.

Run:
    .venv\Scripts\streamlit.exe run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import config
import fields
from classifier import MockClaudeClient, RealClaudeClient
from jira_ticket import build_ticket_text, find_countries
from standardize_file import (
    NEEDS_REVIEW_COLUMN,
    STANDARDIZED_COLUMN,
    detect_country_column,
    detect_value_column,
    read_table,
    standardize_dataframe,
)

st.set_page_config(page_title="Standardization Tool", layout="wide")
st.title("Standardization Tool")
st.caption(
    "Upload a raw-value file, pick which field/taxonomy applies, and get back "
    "the same file with a Standardized Value column added."
)

FIELD_OPTIONS = fields.list_fields()
FIELD_LABELS = {f.key: f"{f.display_name}" for f in FIELD_OPTIONS}

with st.sidebar:
    st.header("1. Choose a field")
    field_key = st.selectbox(
        "Taxonomy field",
        options=[f.key for f in FIELD_OPTIONS],
        format_func=lambda k: FIELD_LABELS[k],
    )
    spec = fields.get(field_key)
    st.caption(f"Prompt file: `{spec.prompt_file}`")
    if spec.notes:
        st.info(spec.notes)

    st.header("2. API mode")
    use_live = st.checkbox(
        "Use real Claude API (--live)",
        value=False,
        help="Off by default — runs a local simulation with no API key and no cost.",
    )
    if use_live and not config.has_real_api_key():
        st.warning(
            "No real ANTHROPIC_API_KEY is configured in .env yet — this run will "
            "fail if you proceed with Live mode checked. Uncheck it to keep "
            "using the simulation, or add a key first."
        )

    st.header("3. Batching")
    batch_size = st.number_input(
        "Batch size (unique values per API call)", min_value=1, value=100, step=10
    )

st.subheader("Upload a file")
uploaded = st.file_uploader("Raw-value file (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])

column_override = None
df_preview = None
if uploaded is not None:
    suffix = Path(uploaded.name).suffix.lower()
    if suffix in (".xlsx", ".xls"):
        df_preview = pd.read_excel(uploaded)
    else:
        df_preview = pd.read_csv(uploaded)

    st.write(f"Loaded **{len(df_preview)}** rows, columns: {list(df_preview.columns)}")
    st.dataframe(df_preview.head(10), width="stretch")

    try:
        auto_col = detect_value_column(df_preview)
        col_help = f"Auto-detected: {auto_col!r}"
    except ValueError:
        auto_col = None
        col_help = "Could not auto-detect — please pick the raw-value column."

    columns = list(df_preview.columns)
    default_index = columns.index(auto_col) if auto_col in columns else 0
    column_override = st.selectbox(
        "Raw-value column", options=columns, index=default_index, help=col_help
    )

run_clicked = st.button("Run", type="primary", disabled=uploaded is None)

if run_clicked and uploaded is not None:
    spec = fields.get(field_key)
    system_prompt = spec.load_prompt()
    blank_fill = spec.standard_values[-1]

    if use_live:
        try:
            client = RealClaudeClient()
        except config.MissingAPIKeyError as exc:
            st.error(f"Cannot use Live mode: {exc}")
            st.stop()
    else:
        client = MockClaudeClient(field_key=field_key)

    if not use_live:
        st.info(
            f"Running in **SIMULATED** mode (client: `{client.name}`) — no API key "
            "used, no cost. Check 'Use real Claude API' in the sidebar once a key "
            "is configured to get real classifications."
        )
        if field_key not in ("positions_designations", "business_legal_form"):
            st.warning(
                f"The simulation has no keyword rules for **{spec.display_name}** yet — "
                f"every value will show as **{blank_fill!r}** in this mock run. This still "
                "proves the upload -> classify -> download pipeline works for this "
                "field; real classification needs Live mode."
            )

    progress = st.progress(0, text="Starting…")
    try:
        raw_col = column_override or detect_value_column(df_preview)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    country_col = detect_country_column(df_preview) if spec.country_dependent else None
    if spec.country_dependent:
        if country_col:
            st.caption(
                f"Country-dependent field: classifying per (country, value) pair "
                f"using column {country_col!r}."
            )
        else:
            st.caption(
                "Country-dependent field, but no country column was found — "
                "falling back to value-only classification."
            )

    progress.progress(30, text="Classifying (checking cache, batching new values)…")
    result_df, stats = standardize_dataframe(
        df_preview, raw_col, system_prompt, client,
        batch_size=int(batch_size), blank_fill=blank_fill,
        country_dependent=spec.country_dependent, country_column=country_col,
    )
    progress.progress(100, text="Done.")

    classified = stats.total_rows - stats.blanks
    st.success(
        f"{stats.total_rows} rows processed — {classified} classified, "
        f"{stats.blanks} blank (auto-filled), {stats.unique_values} unique values sent "
        f"({stats.duplicates_collapsed} duplicates reused, {stats.api_calls_saved} rows "
        "needed no API call)."
    )
    if stats.flagged_count:
        st.warning(
            f"{stats.flagged_count} row(s) flagged in the {NEEDS_REVIEW_COLUMN!r} column "
            "(low/missing confidence, blank input, or API failure) — review these before "
            "treating the rest as final."
        )
    if stats.failed_batches:
        st.error(
            f"{len(stats.failed_batches)} batch(es) failed after retries — those rows "
            f"are marked in both the {STANDARDIZED_COLUMN!r} and {NEEDS_REVIEW_COLUMN!r} columns."
        )

    st.subheader("Result")
    st.dataframe(result_df, width="stretch")

    out_name = f"{Path(uploaded.name).stem}_standardized.xlsx"
    out_path = config.OUTPUT_DIR / out_name
    result_df.to_excel(out_path, index=False)

    with open(out_path, "rb") as fh:
        st.download_button(
            "Download standardized file",
            data=fh.read(),
            file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # Section 5 item 8 — ready-to-paste Jira ticket content (not a live Jira
    # API call — see Section 6). Copy this straight into a new ticket.
    st.subheader("Jira ticket content")
    st.caption(
        "Ready to paste into a new Jira ticket for the engineering handoff — "
        "not a live Jira integration (that's deferred; see Section 6 of the brief)."
    )
    countries = find_countries(df_preview)
    ticket_text = build_ticket_text(spec.display_name, raw_col, countries, out_name)
    st.text_area("Ticket title + description", value=ticket_text, height=280)
    st.download_button(
        "Download ticket text (.txt)",
        data=ticket_text,
        file_name=f"{Path(uploaded.name).stem}_jira_ticket.txt",
        mime="text/plain",
    )
elif uploaded is None:
    st.info("Upload a file to get started.")
