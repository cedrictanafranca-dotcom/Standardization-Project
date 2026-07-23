r"""Step 6 — Simple UI (Streamlit).

A thin wrapper over the Step 3/4/5 pipeline in src/standardize_file.py: upload
a raw-value file, pick the field/taxonomy, hit Run, get a downloadable result.
No new classification logic lives here — this file only handles the UI and
calls into the same functions the CLI (src/standardize_file.py) already uses
and the tests already cover.

Supports two input formats automatically:
  Standard format   — any file with a raw-value column + optional country column.
  Analytics format  — Global Gateway analytics export with countryId / fieldType /
                      inputText columns; field selection is automatic and multiple
                      field types are processed in one run.

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
import corrections as cq
import fields
from analytics_format import (
    RESOLVED_COUNTRY_COLUMN,
    is_analytics_format,
    is_multi_field_standard,
    process_analytics_df,
    process_standard_multi_field_df,
    summarize_field_types,
)
from classifier import MockClaudeClient, RealClaudeClient
from jira_ticket import build_ticket_text, find_countries
from standardize_file import (
    NEEDS_REVIEW_COLUMN,
    REVIEW_REASON_COLUMN,
    STANDARDIZED_COLUMN,
    detect_country_column,
    detect_value_column,
    standardize_dataframe,
)

st.set_page_config(page_title="Standardization Tool", layout="wide")


def _norm_val(v) -> str:
    if v is None:
        return ""
    import math
    if isinstance(v, float) and math.isnan(v):
        return ""
    return " ".join(str(v).split())


def _render_submit_corrections(
    result_df,
    field_key,
    field_display,
    raw_col,
    country_col,
    is_analytics,
    ft_col=None,
    input_col=None,
):
    """Render the 'Submit corrections for review' expander below the download button."""
    with st.expander("Submit corrections for review"):
        st.caption(
            "Download the result, edit the **Standardized Value** column for any rows "
            "you disagree with, then re-upload here. Detected changes will be queued "
            "for a product person to approve or reject on the **Review Corrections** page."
        )

        reviewer_name = st.text_input(
            "Your name", placeholder="e.g. Sarah (Compliance)", key="reviewer_name"
        )
        corrected_file = st.file_uploader(
            "Re-upload corrected file (.xlsx, .csv)",
            type=["xlsx", "xls", "csv"],
            key="corrections_upload",
        )

        if corrected_file is None:
            return

        suffix = Path(corrected_file.name).suffix.lower()
        if suffix in (".xlsx", ".xls"):
            corrected_df = pd.read_excel(corrected_file)
        else:
            corrected_df = pd.read_csv(corrected_file)

        if STANDARDIZED_COLUMN not in corrected_df.columns:
            st.error(f"Uploaded file must contain a '{STANDARDIZED_COLUMN}' column.")
            return

        # Build corrections list by diffing corrected against original result.
        corrections_list = []

        if is_analytics and input_col and ft_col:
            from analytics_format import resolve_field_type
            # Map (inputText, fieldType) → original classification info
            orig_map: dict[tuple, dict] = {}
            for _, row in result_df.iterrows():
                key = (_norm_val(row.get(input_col)), _norm_val(row.get(ft_col)))
                if key not in orig_map:
                    fk = resolve_field_type(str(row.get(ft_col, "")))
                    fd = fields.get(fk).display_name if fk else str(row.get(ft_col, ""))
                    orig_map[key] = {
                        "original": _norm_val(row.get(STANDARDIZED_COLUMN)),
                        "field_key": fk or "",
                        "field_display": fd,
                        "country": _norm_val(row.get(RESOLVED_COUNTRY_COLUMN)),
                    }
            for _, row in corrected_df.iterrows():
                key = (_norm_val(row.get(input_col)), _norm_val(row.get(ft_col)))
                if key not in orig_map:
                    continue
                proposed = _norm_val(row.get(STANDARDIZED_COLUMN))
                original = orig_map[key]["original"]
                raw = _norm_val(row.get(input_col))
                if proposed and proposed != original and raw:
                    corrections_list.append({**orig_map[key], "raw_value": raw, "proposed": proposed})
        else:
            # Standard format: match on (country, raw_value)
            orig_map = {}
            for _, row in result_df.iterrows():
                c = _norm_val(row.get(country_col)) if country_col else ""
                r = _norm_val(row.get(raw_col))
                key = (c, r)
                if key not in orig_map:
                    orig_map[key] = _norm_val(row.get(STANDARDIZED_COLUMN))
            for _, row in corrected_df.iterrows():
                if raw_col not in corrected_df.columns:
                    break
                c = _norm_val(row.get(country_col)) if (country_col and country_col in corrected_df.columns) else ""
                r = _norm_val(row.get(raw_col))
                if not r:
                    continue
                key = (c, r)
                if key not in orig_map:
                    continue
                proposed = _norm_val(row.get(STANDARDIZED_COLUMN))
                original = orig_map[key]
                if proposed and proposed != original:
                    corrections_list.append({
                        "raw_value": r,
                        "field_key": field_key,
                        "field_display": field_display,
                        "country": c,
                        "original": original,
                        "proposed": proposed,
                    })

        # Deduplicate by (field_key, raw_value, country).
        seen: set[tuple] = set()
        unique: list[dict] = []
        for c in corrections_list:
            k = (c["field_key"], c["raw_value"], c["country"])
            if k not in seen:
                unique.append(c)
                seen.add(k)

        if not unique:
            st.info("No differences detected — the Standardized Value column matches the original result.")
            return

        st.write(f"**{len(unique)} correction(s) detected:**")
        st.table(pd.DataFrame([{
            "Field": c["field_display"],
            "Country": c["country"] or "—",
            "Raw Value": c["raw_value"],
            "Original": c["original"],
            "Proposed": c["proposed"],
        } for c in unique]))

        if st.button("Submit for review", type="primary", key="submit_corrections_btn"):
            if not reviewer_name.strip():
                st.warning("Enter your name before submitting.")
                return
            to_queue = [
                cq.make_correction(
                    field_key=c["field_key"],
                    field_display=c["field_display"],
                    raw_value=c["raw_value"],
                    original=c["original"],
                    proposed=c["proposed"],
                    country=c["country"],
                    submitted_by=reviewer_name.strip(),
                )
                for c in unique
            ]
            added = cq.add_to_queue(to_queue)
            st.success(
                f"{added} correction(s) submitted. A product person will review them "
                "on the **Review Corrections** page."
            )
if Path("assets/trulioo_logo.png").exists():
    st.logo("assets/trulioo_logo.png")

st.markdown("""
<style>
/* Sidebar — dark green background with white text */
section[data-testid="stSidebar"] {
    background-color: #0F2A25 !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div {
    color: #FFFFFF !important;
}

/* Info / highlight banners */
div[data-testid="stAlert"] {
    background-color: #DCE9DD !important;
    border-left-color: #1F6E5C !important;
}
</style>
""", unsafe_allow_html=True)

st.title("Standardization Tool")
st.caption(
    "Upload a file — field type is detected automatically from the file structure. "
    "For plain value lists with no field column, use the override below."
)

FIELD_OPTIONS = fields.list_fields()
FIELD_LABELS = {f.key: f"{f.display_name}" for f in FIELD_OPTIONS}

# field_key is only used for single-field standard format files.
# Initialise with a default so it's always defined.
field_key = FIELD_OPTIONS[0].key

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("1. API mode")
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

    st.header("2. Batching")
    batch_size = st.number_input(
        "Batch size (unique values per API call)", min_value=1, value=100, step=10
    )

    st.header("3. Field override")
    st.caption(
        "Only needed for plain value files with no `Field` or `fieldType` column. "
        "For all other files the taxonomy is detected automatically."
    )
    with st.expander("Override field (advanced)"):
        field_key = st.selectbox(
            "Taxonomy field",
            options=[f.key for f in FIELD_OPTIONS],
            format_func=lambda k: FIELD_LABELS[k],
        )
        spec = fields.get(field_key)
        st.caption(f"Prompt file: `{spec.prompt_file}`")
        if spec.notes:
            st.info(spec.notes)

# ── File upload ───────────────────────────────────────────────────────────────

st.subheader("Upload a file")
uploaded = st.file_uploader("Raw-value file (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])

column_override = None
df_preview = None
is_analytics = False
is_multi_standard = False

if uploaded is not None:
    suffix = Path(uploaded.name).suffix.lower()
    if suffix in (".xlsx", ".xls"):
        df_preview = pd.read_excel(uploaded)
    else:
        df_preview = pd.read_csv(uploaded)

    is_analytics = is_analytics_format(df_preview)
    is_multi_standard = not is_analytics and is_multi_field_standard(df_preview)

    st.write(f"Loaded **{len(df_preview)}** rows, columns: {list(df_preview.columns)}")
    st.dataframe(df_preview.head(10), use_container_width=True)

    if is_analytics:
        st.info(
            "**Analytics export detected** — this file has `countryId`, `fieldType`, "
            "and `inputText` columns. Country IDs will be resolved automatically and "
            "each field type will be classified with its matching taxonomy. No manual "
            "field selection needed."
        )
        ft_summary = summarize_field_types(df_preview)
        rows = []
        for item in ft_summary:
            display = item["display_name"] if item.get("display_name") else item["field_type"]
            status = f"→ {display}" if item["known"] else "⚠ No classifier — will be skipped"
            rows.append({
                "Field Type (in file)": item["field_type"],
                "Classifier": status,
                "Rows": item["row_count"],
            })
        st.table(pd.DataFrame(rows))

    elif is_multi_standard:
        # Standard file with a mixed Field column — auto-route each group.
        field_col = next(c for c in df_preview.columns if str(c).strip().lower() == "field")
        from analytics_format import resolve_standard_field
        rows = []
        for ft, group in df_preview.groupby(field_col, dropna=False):
            fk = resolve_standard_field(str(ft))
            display = fields.get(fk).display_name if fk else None
            status = f"→ {display}" if display else "⚠ No classifier — will be skipped"
            rows.append({"Field (in file)": ft, "Classifier": status, "Rows": len(group)})
        st.info(
            "**Mixed-field file detected** — the `Field` column contains multiple "
            "field types. Each will be classified with its matching taxonomy automatically."
        )
        st.table(pd.DataFrame(rows))

    else:
        # Single-field standard format: let user pick the raw-value column.
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

# ── Run button ────────────────────────────────────────────────────────────────

run_clicked = st.button("Run", type="primary", disabled=uploaded is None)

# ── Analytics format processing ───────────────────────────────────────────────

if run_clicked and uploaded is not None and is_analytics:
    if not use_live:
        st.info(
            "Running in **SIMULATED** mode — no API key used, no cost. "
            "Check 'Use real Claude API' in the sidebar for real classifications."
        )

    progress = st.progress(0, text="Resolving country IDs and classifying…")

    result_df, analytics_stats = process_analytics_df(
        df_preview,
        use_live=use_live,
        batch_size=int(batch_size),
    )
    progress.progress(100, text="Done.")

    # ── Per-field stats ───────────────────────────────────────────────────────
    total_flagged = 0
    total_failed = 0
    for fs in analytics_stats.field_summaries:
        if not fs["known"] or fs["stats"] is None:
            continue
        s = fs["stats"]
        classified = s.total_rows - s.blanks
        st.success(
            f"**{fs['field_type']}** ({fs['display_name']}) — "
            f"{s.total_rows} rows, {classified} classified, "
            f"{s.blanks} blank, {s.unique_values} unique values "
            f"({s.api_calls_saved} rows needed no API call)."
        )
        total_flagged += s.flagged_count
        total_failed += len(s.failed_batches)

    if analytics_stats.unknown_field_types:
        st.warning(
            f"Skipped {len(analytics_stats.unknown_field_types)} unknown field type(s): "
            + ", ".join(f"**{t}**" for t in analytics_stats.unknown_field_types)
            + " — rows are marked in the Needs Review column."
        )
    if total_flagged:
        st.warning(
            f"{total_flagged} total row(s) flagged across all field types — "
            f"check the {NEEDS_REVIEW_COLUMN!r} and {REVIEW_REASON_COLUMN!r} columns."
        )
    if total_failed:
        st.error(
            f"{total_failed} batch(es) failed after retries — those rows are marked "
            f"in both the {STANDARDIZED_COLUMN!r} and {NEEDS_REVIEW_COLUMN!r} columns."
        )

    # ── Export column selection ───────────────────────────────────────────────
    st.subheader("Result")

    our_cols = [STANDARDIZED_COLUMN, NEEDS_REVIEW_COLUMN, REVIEW_REASON_COLUMN]
    original_cols = [c for c in result_df.columns if c not in our_cols]

    # Smart defaults for analytics format: Country, fieldType col, inputText col.
    ft_col_actual = next(
        (c for c in original_cols if str(c).lower().strip() == "fieldtype"), None
    )
    input_col_actual = next(
        (c for c in original_cols if str(c).lower().strip() == "inputtext"), None
    )
    default_keep = []
    if RESOLVED_COUNTRY_COLUMN in original_cols:
        default_keep.append(RESOLVED_COUNTRY_COLUMN)
    if ft_col_actual:
        default_keep.append(ft_col_actual)
    if input_col_actual:
        default_keep.append(input_col_actual)

    selected_original = st.multiselect(
        "Columns to include in export",
        options=original_cols,
        default=[c for c in default_keep if c in original_cols],
        help="Standardized Value, Needs Review, and Review Reason are always included.",
    )
    export_df = result_df[selected_original + our_cols]

    st.dataframe(export_df, use_container_width=True)

    out_name = f"{Path(uploaded.name).stem}_standardized.xlsx"
    out_path = config.OUTPUT_DIR / out_name
    export_df.to_excel(out_path, index=False)

    with open(out_path, "rb") as fh:
        st.download_button(
            "Download standardized file",
            data=fh.read(),
            file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    _render_submit_corrections(
        result_df=result_df,
        field_key=None,
        field_display=None,
        raw_col=input_col_actual,
        country_col=RESOLVED_COUNTRY_COLUMN if RESOLVED_COUNTRY_COLUMN in result_df.columns else None,
        is_analytics=True,
        ft_col=ft_col_actual,
        input_col=input_col_actual,
    )

# ── Multi-field standard format processing ───────────────────────────────────

elif run_clicked and uploaded is not None and is_multi_standard:
    if not use_live:
        st.info(
            "Running in **SIMULATED** mode — no API key used, no cost. "
            "Check 'Use real Claude API' in the sidebar for real classifications."
        )

    progress = st.progress(0, text="Classifying each field type…")
    field_col = next(c for c in df_preview.columns if str(c).strip().lower() == "field")
    try:
        value_col = detect_value_column(df_preview)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    country_col = detect_country_column(df_preview)

    result_df, analytics_stats = process_standard_multi_field_df(
        df_preview,
        value_col=value_col,
        country_col=country_col,
        use_live=use_live,
        batch_size=int(batch_size),
    )
    progress.progress(100, text="Done.")

    total_flagged = 0
    total_failed = 0
    for fs in analytics_stats.field_summaries:
        if not fs["known"] or fs["stats"] is None:
            continue
        s = fs["stats"]
        classified = s.total_rows - s.blanks
        st.success(
            f"**{fs['field_type']}** ({fs['display_name']}) — "
            f"{s.total_rows} rows, {classified} classified, "
            f"{s.blanks} blank, {s.unique_values} unique values "
            f"({s.api_calls_saved} rows needed no API call)."
        )
        total_flagged += s.flagged_count
        total_failed += len(s.failed_batches)

    if analytics_stats.unknown_field_types:
        st.warning(
            f"Skipped {len(analytics_stats.unknown_field_types)} unknown field type(s): "
            + ", ".join(f"**{t}**" for t in analytics_stats.unknown_field_types)
            + " — rows are marked in the Needs Review column."
        )
    if total_flagged:
        st.warning(
            f"{total_flagged} row(s) flagged — check the {NEEDS_REVIEW_COLUMN!r} "
            f"and {REVIEW_REASON_COLUMN!r} columns."
        )
    if total_failed:
        st.error(f"{total_failed} batch(es) failed — rows marked in {STANDARDIZED_COLUMN!r}.")

    st.subheader("Result")
    our_cols = [STANDARDIZED_COLUMN, NEEDS_REVIEW_COLUMN, REVIEW_REASON_COLUMN]
    original_cols = [c for c in result_df.columns if c not in our_cols]
    default_keep = [c for c in [country_col, field_col, value_col] if c and c in original_cols]
    selected_original = st.multiselect(
        "Columns to include in export",
        options=original_cols,
        default=default_keep,
        help="Standardized Value, Needs Review, and Review Reason are always included.",
    )
    export_df = result_df[selected_original + our_cols]
    st.dataframe(export_df, use_container_width=True)

    out_name = f"{Path(uploaded.name).stem}_standardized.xlsx"
    out_path = config.OUTPUT_DIR / out_name
    export_df.to_excel(out_path, index=False)
    with open(out_path, "rb") as fh:
        st.download_button(
            "Download standardized file",
            data=fh.read(),
            file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    _render_submit_corrections(
        result_df=result_df,
        field_key=None,
        field_display=None,
        raw_col=value_col,
        country_col=country_col,
        is_analytics=False,
    )

# ── Single-field standard format processing ───────────────────────────────────

elif run_clicked and uploaded is not None and not is_analytics and not is_multi_standard:
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
            f"(LOW/missing confidence, blank input, or API failure) — check the "
            f"{NEEDS_REVIEW_COLUMN!r} column for ranked alternatives and {REVIEW_REASON_COLUMN!r} "
            "for reasoning before treating the rest as final."
        )
    if stats.failed_batches:
        st.error(
            f"{len(stats.failed_batches)} batch(es) failed after retries — those rows "
            f"are marked in both the {STANDARDIZED_COLUMN!r} and {NEEDS_REVIEW_COLUMN!r} columns."
        )

    st.subheader("Result")

    # Export column selection — our three new columns are always included;
    # original columns are opt-in with smart defaults.
    our_cols = [STANDARDIZED_COLUMN, NEEDS_REVIEW_COLUMN, REVIEW_REASON_COLUMN]
    original_cols = [c for c in result_df.columns if c not in our_cols]

    # Default: raw value column + country column (if detected) + "Field" column (if present).
    default_keep = [raw_col]
    if country_col:
        default_keep.insert(0, country_col)
    field_col_match = next(
        (c for c in original_cols if str(c).strip().lower() == "field"), None
    )
    if field_col_match and field_col_match not in default_keep:
        default_keep.append(field_col_match)

    selected_original = st.multiselect(
        "Columns to include in export",
        options=original_cols,
        default=[c for c in default_keep if c in original_cols],
        help="Standardized Value, Needs Review, and Review Reason are always included.",
    )
    export_df = result_df[selected_original + our_cols]

    st.dataframe(export_df, use_container_width=True)

    out_name = f"{Path(uploaded.name).stem}_standardized.xlsx"
    out_path = config.OUTPUT_DIR / out_name
    export_df.to_excel(out_path, index=False)

    with open(out_path, "rb") as fh:
        st.download_button(
            "Download standardized file",
            data=fh.read(),
            file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    _render_submit_corrections(
        result_df=result_df,
        field_key=field_key,
        field_display=spec.display_name,
        raw_col=raw_col,
        country_col=country_col,
        is_analytics=False,
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
