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
import master_lookup as _ml
from analytics_format import (
    RESOLVED_COUNTRY_COLUMN,
    is_analytics_format,
    is_multi_field_standard,
    process_analytics_df,
    process_standard_multi_field_df,
    summarize_field_types,
)
from classifier import MockClaudeClient, RealClaudeClient
from developer_export import build_developer_export, ready_script_text
from jira_ticket import build_ticket_text, find_countries
from mapping_reason import build_reviewed_selection_reason
from review_resolution import resolve_review_field_key
from standardize_file import (
    MAPPING_REASON_COLUMN,
    NEEDS_REVIEW_COLUMN,
    REVIEW_REASON_COLUMN,
    STANDARDIZED_COLUMN,
    detect_country_column,
    detect_value_column,
    reload_lookup,
    standardize_dataframe,
)
from ui_theme import apply_brand_theme


def _norm_val(v) -> str:
    if v is None:
        return ""
    import math
    if isinstance(v, float) and math.isnan(v):
        return ""
    return " ".join(str(v).split())


def _render_run_summary(
    result_df: pd.DataFrame,
    value_col: str,
    field_summaries: list[dict] | None = None,
    field_col: str | None = None,
) -> None:
    """Render a confidence breakdown summary after a run."""
    nr = result_df[NEEDS_REVIEW_COLUMN].fillna("").astype(str)
    rr = result_df[REVIEW_REASON_COLUMN].fillna("").astype(str)
    raw = result_df[value_col].fillna("").astype(str).str.strip()

    blank_mask = raw == ""
    low_mask = nr.str.startswith(NEEDS_REVIEW_COLUMN) & ~blank_mask
    med_mask = (~nr.str.startswith(NEEDS_REVIEW_COLUMN)) & (rr != "")
    high_mask = (~nr.str.startswith(NEEDS_REVIEW_COLUMN)) & (rr == "") & ~blank_mask

    total = len(result_df)
    high_n = int(high_mask.sum())
    med_n = int(med_mask.sum())
    low_n = int(low_mask.sum())
    blank_n = int(blank_mask.sum())

    st.subheader("Run Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("HIGH confidence", high_n, f"{high_n / total:.0%}" if total else "—")
    c2.metric("MEDIUM confidence", med_n, f"{med_n / total:.0%}" if total else "—")
    c3.metric("LOW — Needs Review", low_n, f"{low_n / total:.0%}" if total else "—")
    c4.metric("Blank (auto-filled)", blank_n, f"{blank_n / total:.0%}" if total else "—")

    if low_n:
        st.warning(
            f"**{low_n} row(s) flagged for review.** "
            "Check the **Needs Review** column for ranked alternatives and "
            "**Mapping Reason** for the decision explanation. "
            "Use **Submit corrections for review** below to flag any disagreements."
        )
    if med_n:
        st.info(
            f"**{med_n} row(s) classified with MEDIUM confidence** — accepted but involved judgment. "
            "Review the **Mapping Reason** column before treating these as final."
        )

    # Per-field breakdown table for mixed-field runs.
    if field_col and field_col in result_df.columns and field_summaries:
        rows = []
        for fs in field_summaries:
            if not fs.get("known"):
                continue
            ft_mask = result_df[field_col].astype(str).str.strip() == str(fs["field_type"]).strip()
            sub_nr = nr[ft_mask]
            sub_rr = rr[ft_mask]
            sub_raw = raw[ft_mask]
            sub_blank = int((sub_raw == "").sum())
            sub_low = int((sub_nr.str.startswith(NEEDS_REVIEW_COLUMN) & (sub_raw != "")).sum())
            sub_med = int(((~sub_nr.str.startswith(NEEDS_REVIEW_COLUMN)) & (sub_rr != "")).sum())
            sub_high = int(
                ((~sub_nr.str.startswith(NEEDS_REVIEW_COLUMN)) & (sub_rr == "") & (sub_raw != "")).sum()
            )
            rows.append({
                "Field": fs.get("display_name", fs["field_type"]),
                "Total": len(sub_nr),
                "HIGH": sub_high,
                "MEDIUM": sub_med,
                "LOW / Review": sub_low,
                "Blank": sub_blank,
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_lookup_update(field_summaries: list[dict]) -> None:
    """Show a button to add new HIGH confidence API results to the lookup table."""
    new_by_field: dict[str, dict] = {}
    for fs in field_summaries:
        if fs.get("known") and fs.get("stats") and fs["stats"].new_mappings:
            new_by_field[fs["field_key"]] = fs["stats"].new_mappings

    total_new = sum(len(v) for v in new_by_field.values())
    if total_new == 0:
        return

    breakdown = ", ".join(
        f"{fields.get(fk).display_name} ({len(m)})"
        for fk, m in new_by_field.items()
    )
    with st.expander(f"Add {total_new} new mapping(s) to lookup — avoid re-classifying in future runs"):
        st.caption(
            f"The API classified {total_new} value(s) with HIGH confidence that aren't in the lookup yet: "
            f"{breakdown}. Adding them means future runs resolve these instantly without an API call."
        )
        if st.button("Add to lookup", key="update_lookup_btn", type="primary"):
            added = 0
            for fk, mappings in new_by_field.items():
                spec_fk = fields.get(fk)
                added += _ml.merge_api_results(fk, mappings, spec_fk.country_dependent)
            reload_lookup()
            st.success(f"Added {added} new entry(s) to the lookup. Active immediately for this session.")


def _render_flagged_review(rr: dict) -> pd.DataFrame:
    """Show inline review UI for flagged rows. Returns (possibly updated) result_df."""
    result_df = rr["result_df"]
    value_col = rr.get("value_col")
    country_col = rr.get("country_col")
    field_col = rr.get("field_col")
    run_type = rr.get("run_type")

    if not value_col or value_col not in result_df.columns:
        return result_df

    nr = result_df[NEEDS_REVIEW_COLUMN].fillna("").astype(str)
    raw = result_df[value_col].fillna("").astype(str).str.strip()
    flagged_idx = result_df.index[nr.str.startswith(NEEDS_REVIEW_COLUMN) & (raw != "")].tolist()

    if not flagged_idx:
        return result_df

    # For single-field runs, use the run-level display name.
    single_field_display = rr.get("field_display") or (
        rr["spec"].display_name if rr.get("spec") else None
    )

    st.subheader(f"Review {len(flagged_idx)} Flagged Row(s)")
    st.caption(
        "These rows were classified with LOW confidence or had issues. "
        "Choose the correct value for each, then click **Confirm selections**."
    )

    with st.form("flagged_review_form"):
        selections: dict[int, str] = {}

        for i, idx in enumerate(flagged_idx):
            row = result_df.loc[idx]
            raw_val = _norm_val(row.get(value_col))
            country = (
                _norm_val(row.get(country_col))
                if country_col and country_col in result_df.columns
                else ""
            )
            current_std = _norm_val(row.get(STANDARDIZED_COLUMN))
            nr_val = _norm_val(row.get(NEEDS_REVIEW_COLUMN))
            reason = (
                _norm_val(row.get(MAPPING_REASON_COLUMN))
                if MAPPING_REASON_COLUMN in result_df.columns
                else _norm_val(row.get(REVIEW_REASON_COLUMN))
                if REVIEW_REASON_COLUMN in result_df.columns
                else ""
            )
            ft_val = (
                _norm_val(row.get(field_col))
                if field_col and field_col in result_df.columns
                else ""
            )

            # Parse alternatives from "Needs Review: alt1 | alt2" format.
            alts: list[str] = []
            prefix = NEEDS_REVIEW_COLUMN + ": "
            if nr_val.startswith(prefix):
                alt_text = nr_val[len(prefix):].replace(" | ", " / ")
                alts = [a.strip().rstrip("?") for a in alt_text.split(" / ") if a.strip()]

            # Resolve both original input labels and normalized output labels.
            # Example: a summary may say "Standardized Position" while the
            # result row says "Universal Position".
            row_field_key = resolve_review_field_key(
                ft_val,
                rr.get("field_summaries", []),
                rr.get("field_key"),
            )

            # Options = the field's full canonical standard values only.
            options: list[str] = []
            row_spec = None
            if run_type == "single_field" and rr.get("spec"):
                row_spec = rr["spec"]
            elif row_field_key:
                try:
                    row_spec = fields.get(row_field_key)
                except KeyError:
                    row_spec = None
            if row_spec:
                options = list(row_spec.standard_values)
            if not options:
                options = [v for v in ([current_std] + alts) if v] or ["Unknown"]

            # Pre-select Suggestion 1 if it appears in the canonical list.
            # Fall back to the catch-all (last item) when there are no suggestions
            # rather than defaulting to index 0 (which is always Board Member).
            default_idx = len(options) - 1
            if alts and alts[0] in options:
                default_idx = options.index(alts[0])
            elif current_std in options:
                default_idx = options.index(current_std)

            # Resolve human-readable field type label.
            if row_spec:
                field_label = row_spec.display_name
            elif run_type == "single_field" and single_field_display:
                field_label = single_field_display
            else:
                field_label = ft_val or None

            # Header: raw value · country, then field type on its own line.
            header_parts = [f"**{raw_val}**"]
            if country:
                header_parts.append(f"· {country}")
            st.markdown(" ".join(header_parts))
            if field_label:
                st.caption(f"Field type: {field_label}")

            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown(f"**Current classification:** {current_std or '—'}")
                if alts:
                    suggestions = " / ".join(alts[:2])
                    st.markdown(f"**Suggested:** {suggestions}")
                else:
                    st.markdown("**Suggested:** *(no alternatives — model was certain)*")
                if reason:
                    st.markdown(f"**Mapping reason:** {reason}")
            with col2:
                selections[idx] = st.selectbox(
                    "Set final classification",
                    options=options,
                    index=default_idx,
                    key=f"review_sel_{idx}",
                )

            if i < len(flagged_idx) - 1:
                st.divider()

        submitted = st.form_submit_button("Confirm selections", type="primary")

    if submitted:
        updated = result_df.copy()

        pending_saves = []
        for idx, new_val in selections.items():
            row = result_df.loc[idx]
            raw = _norm_val(row.get(value_col))
            country_val = (
                _norm_val(row.get(country_col))
                if country_col and country_col in result_df.columns
                else ""
            )
            ft = (
                str(row.get(field_col, "")).strip()
                if field_col and field_col in result_df.columns
                else ""
            )
            fk = resolve_review_field_key(
                ft,
                rr.get("field_summaries", []),
                rr.get("field_key"),
            )

            previous_value = _norm_val(row.get(STANDARDIZED_COLUMN))
            updated.at[idx, STANDARDIZED_COLUMN] = new_val
            updated.at[idx, MAPPING_REASON_COLUMN] = build_reviewed_selection_reason(
                field_key=fk,
                raw_value=raw,
                standardized_value=new_val,
                country=country_val,
                previous_value=previous_value,
                confirmed=new_val == previous_value,
            )
            updated.at[idx, NEEDS_REVIEW_COLUMN] = ""
            updated.at[idx, REVIEW_REASON_COLUMN] = ""

            if raw and fk and new_val:
                try:
                    sp = fields.get(fk)
                    country_dep = sp.country_dependent
                    display = sp.display_name
                except Exception:
                    country_dep = False
                    display = fk
                pending_saves.append({
                    "field_key": fk,
                    "display": display,
                    "raw": raw,
                    "country": country_val if country_dep else "",
                    "std_val": new_val,
                    "country_dependent": country_dep,
                })

        rr["result_df"] = updated
        rr["pending_lookup_saves"] = pending_saves
        st.session_state["run_result"] = rr
        st.success(f"{len(selections)} row(s) confirmed. Save them to the lookup below so they never flag again.")
        return updated

    return result_df


def _render_pending_lookup_saves(rr: dict) -> None:
    """After confirming flagged rows, offer to save those decisions to the lookup."""
    pending = rr.get("pending_lookup_saves")
    if not pending:
        return

    with st.expander(f"Save {len(pending)} confirmed mapping(s) to lookup — avoid re-flagging in future runs", expanded=True):
        st.caption(
            "These are the values you just confirmed. Saving them means future runs resolve "
            "them instantly without an API call and without flagging them again."
        )

        save_flags: dict[int, bool] = {}
        for i, item in enumerate(pending):
            label = f"**{item['raw']}** → {item['std_val']}"
            if item.get("country"):
                label += f"  *(for {item['country']} only)*"
            else:
                label += "  *(all countries)*"
            save_flags[i] = st.checkbox(label, value=True, key=f"pending_save_{i}")

        if st.button("Save selected to lookup", key="pending_save_btn", type="primary"):
            to_save = [item for i, item in enumerate(pending) if save_flags.get(i)]
            total_added = 0
            try:
                for item in to_save:
                    total_added += _ml.merge_api_results(
                        item["field_key"],
                        {(item["country"], item["raw"]): item["std_val"]},
                        item["country_dependent"],
                    )
                reload_lookup()
                rr["pending_lookup_saves"] = None
                st.session_state["run_result"] = rr
                if total_added:
                    st.success(f"Saved {total_added} new entry(s) to the lookup. Active immediately.")
                else:
                    st.info("All selected entries were already in the lookup — nothing new added.")
            except Exception as exc:
                st.error(f"Failed to save: {exc}")


def _render_manual_lookup_add(field_summaries: list[dict]) -> None:
    """Show a form to manually add a single lookup entry."""
    known = [fs for fs in field_summaries if fs.get("known") and fs.get("field_key")]
    if not known:
        return

    with st.expander("Manually add a lookup entry"):
        st.caption(
            "Add a raw value → standardized value mapping directly to the lookup table. "
            "Future runs will use this instead of calling the API."
        )

        field_options = {fs["field_key"]: fs.get("display_name", fs["field_key"]) for fs in known}
        selected_fk = st.selectbox(
            "Field",
            options=list(field_options.keys()),
            format_func=lambda k: field_options[k],
            key="manual_lookup_field",
        )
        spec_ml = fields.get(selected_fk)

        raw_input = st.text_input("Raw value (exact, case-sensitive)", key="manual_lookup_raw")
        country_input = ""
        if spec_ml.country_dependent:
            country_input = st.text_input(
                "Country (leave blank for country-agnostic)",
                key="manual_lookup_country",
            )
        std_val = st.selectbox(
            "Standardized value",
            options=spec_ml.standard_values,
            key="manual_lookup_std",
        )

        if st.button("Add to lookup", key="manual_lookup_btn", type="primary"):
            if not raw_input.strip():
                st.warning("Enter a raw value.")
            else:
                try:
                    from standardize_file import _norm_key
                    norm_raw = _norm_key(raw_input.strip())
                    norm_country = _norm_key(country_input.strip()) if country_input else ""
                    added = _ml.merge_api_results(
                        selected_fk,
                        {(norm_country, norm_raw): std_val},
                        spec_ml.country_dependent,
                    )
                    reload_lookup()
                    if added:
                        st.success(f"Added: {raw_input.strip()!r} → {std_val!r}. Active immediately.")
                    else:
                        st.warning(
                            f"{raw_input.strip()!r} already exists in the lookup for this field. "
                            "To override an existing mapping, edit the lookup file directly."
                        )
                except Exception as exc:
                    st.error(f"Failed to save: {exc}")


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
            if raw_col not in corrected_df.columns:
                st.error(f"Uploaded file is missing the '{raw_col}' column.")
                return
            for _, row in corrected_df.iterrows():
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
apply_brand_theme()

st.title("Standardization Tool")
st.caption(
    "Upload a file — field type is detected automatically from the file structure. "
    "For plain value lists with no field column, use the override below."
)
st.page_link(
    "pages/1_Help_and_Field_Guide.py",
    label="First time? Open the Help & Field Guide",
    icon="📘",
)

FIELD_OPTIONS = fields.list_fields()
FIELD_LABELS = {f.key: f"{f.display_name}" for f in FIELD_OPTIONS}

# field_key is only used for single-field standard format files.
# Initialise with a default so it's always defined.
field_key = FIELD_OPTIONS[0].key

# ── Run settings ─────────────────────────────────────────────────────────────

with st.expander("Run settings", expanded=False):
    settings_api, settings_batch, settings_volume = st.columns(3)
    with settings_api:
        use_live = st.checkbox(
            "Use real Claude API",
            value=False,
            help="Off by default — runs a local simulation with no API key and no cost.",
        )
    with settings_batch:
        batch_size = st.number_input(
            "Batch size", min_value=1, value=100, step=10,
            help="Unique values sent in each API request.",
        )
    with settings_volume:
        min_count = st.number_input(
            "Minimum value count",
            min_value=1,
            value=50,
            step=10,
            help="Values appearing fewer times are excluded from the output.",
        )

    if use_live and not config.has_real_api_key():
        st.warning(
            "No real ANTHROPIC_API_KEY is configured. Turn off the real API setting "
            "to use the simulation, or configure the key before continuing."
        )

    st.markdown("**Field override (advanced)**")
    st.caption(
        "Use only for a plain value file with no Field or fieldType column. "
        "Other files are detected automatically."
    )
    field_key = st.selectbox(
        "Field used for a plain value file",
        options=[f.key for f in FIELD_OPTIONS],
        format_func=lambda k: FIELD_LABELS[k],
    )
    spec = fields.get(field_key)
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
        sheets = pd.read_excel(uploaded, sheet_name=None)
        if len(sheets) > 1:
            from analytics_format import resolve_standard_field
            parts = []
            matched_sheets = []
            unmatched_sheets = []
            for sheet_name, sheet_df in sheets.items():
                if sheet_df.empty:
                    continue
                # Inject a Field column from the sheet name so each group routes
                # to the correct classifier automatically.
                sheet_df = sheet_df.copy()
                sheet_df["Field"] = sheet_name
                fk = resolve_standard_field(sheet_name)
                if fk is not None:
                    matched_sheets.append(sheet_name)
                else:
                    unmatched_sheets.append(sheet_name)
                parts.append(sheet_df)
            df_preview = pd.concat(parts, ignore_index=True) if parts else next(iter(sheets.values()))
            msg = (
                f"**{len(sheets)} sheet(s) detected** — combined into {len(df_preview)} rows. "
                f"{len(matched_sheets)} sheet(s) matched a classifier: {', '.join(matched_sheets)}."
            )
            if unmatched_sheets:
                msg += f" {len(unmatched_sheets)} sheet(s) have no classifier and will be skipped: {', '.join(unmatched_sheets)}."
            st.info(msg)
        else:
            df_preview = next(iter(sheets.values()))
    else:
        df_preview = pd.read_csv(uploaded)

    is_analytics = is_analytics_format(df_preview)
    is_multi_standard = not is_analytics and is_multi_field_standard(df_preview)

    # Clear stale session state when a different file is uploaded.
    if (
        st.session_state.get('run_result')
        and st.session_state['run_result'].get('filename') != uploaded.name
    ):
        st.session_state.pop('run_result', None)

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
        from analytics_format import find_field_col, resolve_standard_field
        field_col = find_field_col(df_preview)
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
        min_count=int(min_count),
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
            f"({s.api_calls_saved} rows needed no API call; "
            f"{s.lookup_hits} exact lookup, "
            f"{s.alias_matches} approved alias, "
            f"{s.similarity_predictions} opt-in predictive lookup, "
            f"{s.retrieval_assisted} retrieval-assisted API, "
            f"{s.semantic_retrievals} with semantic evidence)."
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
            f"check the {NEEDS_REVIEW_COLUMN!r} and {MAPPING_REASON_COLUMN!r} columns."
        )
    if total_failed:
        st.error(
            f"{total_failed} batch(es) failed after retries — those rows are marked "
            f"in both the {STANDARDIZED_COLUMN!r} and {NEEDS_REVIEW_COLUMN!r} columns."
        )

    our_cols = [
        STANDARDIZED_COLUMN,
        MAPPING_REASON_COLUMN,
        NEEDS_REVIEW_COLUMN,
        REVIEW_REASON_COLUMN,
    ]
    original_cols = [c for c in result_df.columns if c not in our_cols]

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

    st.session_state['run_result'] = {
        'run_type': 'analytics',
        'result_df': result_df,
        'filename': uploaded.name,
        'value_col': input_col_actual,
        'field_col': ft_col_actual,
        'ft_col': ft_col_actual,
        'input_col': input_col_actual,
        'country_col': RESOLVED_COUNTRY_COLUMN if RESOLVED_COUNTRY_COLUMN in result_df.columns else None,
        'field_summaries': analytics_stats.field_summaries,
        'is_analytics': True,
        'original_cols': original_cols,
        'default_keep': default_keep,
        'field_key': None,
        'field_display': None,
        'spec': None,
    }

# ── Multi-field standard format processing ───────────────────────────────────

elif run_clicked and uploaded is not None and is_multi_standard:
    if not use_live:
        st.info(
            "Running in **SIMULATED** mode — no API key used, no cost. "
            "Check 'Use real Claude API' in the sidebar for real classifications."
        )

    progress = st.progress(0, text="Classifying each field type…")
    from analytics_format import find_field_col as _find_field_col
    field_col = _find_field_col(df_preview)
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
        min_count=int(min_count),
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
            f"({s.api_calls_saved} rows needed no API call; "
            f"{s.lookup_hits} exact lookup, "
            f"{s.alias_matches} approved alias, "
            f"{s.similarity_predictions} opt-in predictive lookup, "
            f"{s.retrieval_assisted} retrieval-assisted API, "
            f"{s.semantic_retrievals} with semantic evidence)."
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
            f"and {MAPPING_REASON_COLUMN!r} columns."
        )
    if total_failed:
        st.error(f"{total_failed} batch(es) failed — rows marked in {STANDARDIZED_COLUMN!r}.")

    our_cols = [
        STANDARDIZED_COLUMN,
        MAPPING_REASON_COLUMN,
        NEEDS_REVIEW_COLUMN,
        REVIEW_REASON_COLUMN,
    ]
    original_cols = [c for c in result_df.columns if c not in our_cols]
    default_keep = [c for c in [country_col, field_col, value_col] if c and c in original_cols]

    st.session_state['run_result'] = {
        'run_type': 'multi_field',
        'result_df': result_df,
        'filename': uploaded.name,
        'value_col': value_col,
        'field_col': field_col,
        'ft_col': None,
        'input_col': None,
        'country_col': country_col,
        'field_summaries': analytics_stats.field_summaries,
        'is_analytics': False,
        'original_cols': original_cols,
        'default_keep': default_keep,
        'field_key': None,
        'field_display': None,
        'spec': None,
    }

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
    # Filter single-field files by volume column or raw value occurrence count.
    if int(min_count) > 0:
        _vol_col = next(
            (c for c in df_preview.columns if str(c).strip().lower() in ("volume", "value #a")), None
        )
        if _vol_col:
            df_preview = df_preview[
                pd.to_numeric(df_preview[_vol_col], errors="coerce").fillna(0) >= int(min_count)
            ].reset_index(drop=True)
        else:
            from standardize_file import _norm_key as _nk
            _raw_series = df_preview[raw_col].apply(_nk)
            _counts = _raw_series.value_counts()
            df_preview = df_preview[_raw_series.map(_counts).fillna(0) >= int(min_count)].reset_index(drop=True)

    result_df, stats = standardize_dataframe(
        df_preview, raw_col, system_prompt, client,
        batch_size=int(batch_size), blank_fill=blank_fill,
        country_dependent=spec.country_dependent, country_column=country_col,
        field_key=field_key,
        canonical_values=spec.standard_values,
    )
    progress.progress(100, text="Done.")

    classified = stats.total_rows - stats.blanks
    st.success(
        f"{stats.total_rows} rows processed — {classified} classified, "
        f"{stats.blanks} blank (auto-filled), {stats.unique_values} unique values sent "
        f"({stats.duplicates_collapsed} duplicates reused, {stats.api_calls_saved} rows "
        "needed no API call)."
    )
    if (
        stats.alias_matches
        or stats.alias_deferred
        or stats.alias_reviews
        or stats.similarity_predictions
        or stats.retrieval_assisted
        or stats.semantic_retrievals
    ):
        st.info(
            f"Approved mappings also supported this run: "
            f"{stats.alias_matches} safe alias match(es); "
            f"{stats.alias_deferred} alias match(es) sent to the classifier; "
            f"{stats.alias_reviews} modifier case(s) forced to review; "
            f"{stats.similarity_predictions} opt-in similar-value prediction(s); "
            f"{stats.retrieval_assisted} classifier value(s) received approved examples; "
            f"{stats.semantic_retrievals} received semantic evidence."
        )
    if stats.flagged_count:
        st.warning(
            f"{stats.flagged_count} row(s) flagged in the {NEEDS_REVIEW_COLUMN!r} column "
            f"(LOW/missing confidence, blank input, or API failure) — check the "
            f"{NEEDS_REVIEW_COLUMN!r} column for ranked alternatives and {MAPPING_REASON_COLUMN!r} "
            "for reasoning before treating the rest as final."
        )
    if stats.failed_batches:
        st.error(
            f"{len(stats.failed_batches)} batch(es) failed after retries — those rows "
            f"are marked in both the {STANDARDIZED_COLUMN!r} and {NEEDS_REVIEW_COLUMN!r} columns."
        )

    our_cols = [
        STANDARDIZED_COLUMN,
        MAPPING_REASON_COLUMN,
        NEEDS_REVIEW_COLUMN,
        REVIEW_REASON_COLUMN,
    ]
    original_cols = [c for c in result_df.columns if c not in our_cols]
    default_keep = [raw_col]
    if country_col:
        default_keep.insert(0, country_col)
    from analytics_format import find_field_col as _ffc
    field_col_match = _ffc(pd.DataFrame(columns=original_cols))
    if field_col_match and field_col_match not in default_keep:
        default_keep.append(field_col_match)

    st.session_state['run_result'] = {
        'run_type': 'single_field',
        'result_df': result_df,
        'filename': uploaded.name,
        'value_col': raw_col,
        'field_col': None,
        'ft_col': None,
        'input_col': None,
        'country_col': country_col,
        'field_summaries': [{'field_key': field_key, 'known': True, 'stats': stats}],
        'is_analytics': False,
        'original_cols': original_cols,
        'default_keep': default_keep,
        'field_key': field_key,
        'field_display': spec.display_name,
        'spec': spec,
    }

# ── Post-run display (persistent across reruns via session state) ─────────────
_rr = st.session_state.get('run_result')
if _rr is not None:
    _result_df = _render_flagged_review(_rr)

    if _rr.get('value_col'):
        _render_run_summary(
            _result_df,
            _rr['value_col'],
            field_summaries=_rr.get('field_summaries'),
            field_col=_rr.get('field_col'),
        )

    _our_cols = [
        STANDARDIZED_COLUMN,
        MAPPING_REASON_COLUMN,
        NEEDS_REVIEW_COLUMN,
        REVIEW_REASON_COLUMN,
    ]
    st.subheader("Result")
    _selected_original = st.multiselect(
        "Columns to include in export",
        options=_rr['original_cols'],
        default=[c for c in _rr['default_keep'] if c in _rr['original_cols']],
        help=(
            "Standardized Value, Mapping Reason, Needs Review, and Review Reason "
            "are always included."
        ),
    )
    _export_df = _result_df[
        [c for c in _selected_original if c in _result_df.columns]
        + [c for c in _our_cols if c in _result_df.columns]
    ]
    st.dataframe(_export_df, use_container_width=True)

    _out_name = f"{Path(_rr['filename']).stem}_standardized.xlsx"
    _out_path = config.OUTPUT_DIR / _out_name
    _developer_df = build_developer_export(
        _result_df,
        raw_col=_rr.get('value_col'),
        country_col=_rr.get('country_col'),
        fixed_field_key=_rr.get('field_key'),
        field_col=_rr.get('field_col'),
    )
    with pd.ExcelWriter(_out_path, engine="openpyxl") as _writer:
        _export_df.to_excel(_writer, index=False, sheet_name="Standardized Data")
        _developer_df.to_excel(_writer, index=False, sheet_name="Developer Script")
    with open(_out_path, "rb") as _fh:
        st.download_button(
            "Download standardized file",
            data=_fh.read(),
            file_name=_out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with st.expander("Developer handoff export (optional)"):
        st.write(
            "The Excel download includes a **Developer Script** worksheet. It formats the final "
            "mappings but never changes or decides them."
        )
        _ready_script = ready_script_text(_developer_df)
        _ready_count = int(
            _developer_df["Status"].astype(str).str.startswith("Ready").sum()
        ) if not _developer_df.empty else 0
        _needs_setup_count = len(_developer_df) - _ready_count
        _dev_col1, _dev_col2 = st.columns(2)
        _dev_col1.metric("Ready script lines", _ready_count)
        _dev_col2.metric("Need confirmation or excluded", _needs_setup_count)
        st.dataframe(_developer_df, width="stretch", hide_index=True)
        if _ready_script:
            st.download_button(
                "Download developer script (.cs)",
                data=_ready_script,
                file_name=f"{Path(_rr['filename']).stem}_standardizations.cs",
                mime="text/plain",
            )
        else:
            st.info(
                "No paste-ready lines are available yet. Check the Status column—most fields "
                "still need their constructor name confirmed."
            )
        st.caption(
            "The ~value~ format follows the developer example provided. Constructor names are "
            "best-effort placeholders for demonstration and are labeled provisional until confirmed."
        )

    _render_pending_lookup_saves(_rr)
    _render_lookup_update(_rr['field_summaries'])
    _render_manual_lookup_add(_rr['field_summaries'])

    _render_submit_corrections(
        result_df=_result_df,
        field_key=_rr.get('field_key'),
        field_display=_rr.get('field_display'),
        raw_col=_rr.get('value_col'),
        country_col=_rr.get('country_col'),
        is_analytics=_rr['is_analytics'],
        ft_col=_rr.get('ft_col'),
        input_col=_rr.get('input_col'),
    )

    if _rr['run_type'] == 'single_field' and _rr.get('spec'):
        _spec = _rr['spec']
        st.subheader("Jira ticket content")
        st.caption(
            "Ready to paste into a new Jira ticket for the engineering handoff — "
            "not a live Jira integration (that's deferred; see Section 6 of the brief)."
        )
        _countries = find_countries(_result_df)
        _ticket_text = build_ticket_text(_spec.display_name, _rr['value_col'], _countries, _out_name)
        st.text_area("Ticket title + description", value=_ticket_text, height=280)
        st.download_button(
            "Download ticket text (.txt)",
            data=_ticket_text,
            file_name=f"{Path(_rr['filename']).stem}_jira_ticket.txt",
            mime="text/plain",
        )

if uploaded is None and not st.session_state.get('run_result'):
    st.info("Upload a file to get started.")
