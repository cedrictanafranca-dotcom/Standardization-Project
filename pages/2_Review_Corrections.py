"""Review Corrections — product person approval queue.

Product persons open this page to approve or reject corrections submitted by
reviewers. Approved corrections are written to data/master_lookup.json so
future runs resolve those values without an API call.

Demo mode: load 5 realistic sample corrections to walk through the workflow
in a presentation without needing a real file to have been processed first.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import corrections as cq
from ui_theme import apply_brand_theme

apply_brand_theme()

# ── Page header ───────────────────────────────────────────────────────────────

pending = cq.get_pending()
history = cq.get_history()

st.title("Correction Review Queue")
st.caption(
    "Corrections submitted by reviewers appear here. Approve to reuse the value "
    "without another API call, reject to discard it, or flag a recurring pattern "
    "for a broader rule update."
)

with st.expander("Demo controls"):
    st.caption(
        "Load realistic sample corrections to walk through the approval workflow "
        "in a presentation."
    )
    if st.button("Load demo data", type="primary"):
        demo = cq.load_demo_corrections()
        added = cq.add_to_queue(demo)
        if added:
            st.success(f"Loaded {added} demo correction(s) into the queue.")
        else:
            st.info("Demo corrections are already in the queue.")
        st.rerun()

    if st.button("Clear demo data"):
        removed = cq.clear_demo_data()
        if removed:
            st.success(f"Removed {removed} demo item(s).")
        else:
            st.info("No demo data to clear.")
        st.rerun()

tab_pending, tab_history = st.tabs([
    f"Pending ({len(pending)})",
    f"History ({len(history)})",
])

# ── Pending tab ───────────────────────────────────────────────────────────────

with tab_pending:
    if not pending:
        st.info(
            "No corrections pending. Reviewers submit corrections from the main page "
            "after running a file. Use **Demo controls** above to see a "
            "walkthrough example."
        )
    else:
        # Bulk actions
        col_approve_all, col_reject_all, _ = st.columns([1, 1, 4])
        with col_approve_all:
            if st.button("Approve all", type="primary"):
                for c in pending:
                    cq.approve(c["id"])
                st.rerun()
        with col_reject_all:
            if st.button("Reject all"):
                for c in pending:
                    cq.reject(c["id"])
                st.rerun()

        st.divider()

        for c in pending:
            is_demo = c.get("source") == "demo"
            demo_badge = " — *demo*" if is_demo else ""

            with st.container(border=True):
                # Header row: field, country, date
                col_meta, col_submitted = st.columns([3, 1])
                with col_meta:
                    field_badge = (
                        f"<span style='"
                        f"background:rgba(0,107,98,0.1);color:#006B62;font-weight:600;"
                        f"padding:3px 10px;border-radius:20px;font-size:12px;"
                        f"letter-spacing:0.01em'>{c['field_display']}</span>"
                    )
                    country_str = c['country'] or '*(no country)*'
                    st.markdown(
                        f"{field_badge}&nbsp;&nbsp;{country_str}" + demo_badge,
                        unsafe_allow_html=True,
                    )
                with col_submitted:
                    submitted_date = c["submitted_at"][:10]
                    st.caption(f"Submitted {submitted_date} by {c['submitted_by'] or 'unknown'}")

                # Before → After
                st.markdown(
                    f"<div style='font-size:0.855rem;margin:0.5rem 0'>"
                    f"<code style='background:#F7F8FA;padding:2px 6px;border-radius:4px;font-size:0.82rem'>{c['raw_value']}</code>"
                    f"<br/><span style='color:#5E6B74'>Original:</span> "
                    f"<strong>{c['original']}</strong>"
                    f"&nbsp;&nbsp;→&nbsp;&nbsp;"
                    f"<span style='color:#006B62'>Proposed:</span> "
                    f"<strong>{c['proposed']}</strong>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                # Reviewer inputs
                note = st.text_input(
                    "Note (optional)",
                    key=f"note_{c['id']}",
                    placeholder="e.g. Valid for LatAm registries — see Argentina corporate law",
                )
                flag = st.checkbox(
                    "Flag for prompt update",
                    key=f"flag_{c['id']}",
                    help="Check if this pattern recurs enough to warrant a rule change in the taxonomy prompt file.",
                )

                # Action buttons
                col_approve, col_reject, _ = st.columns([1, 1, 4])
                with col_approve:
                    if st.button("Approve", key=f"approve_{c['id']}", type="primary"):
                        cq.approve(c["id"], note=note, needs_prompt_update=flag)
                        st.rerun()
                with col_reject:
                    if st.button("Reject", key=f"reject_{c['id']}"):
                        cq.reject(c["id"], note=note)
                        st.rerun()

# ── History tab ───────────────────────────────────────────────────────────────

with tab_history:
    if not history:
        st.info("No corrections have been reviewed yet.")
    else:
        prompt_updates = [c for c in history if c.get("needs_prompt_update") and c["status"] == "approved"]
        if prompt_updates:
            st.warning(
                f"**{len(prompt_updates)} approved correction(s) flagged for prompt update** — "
                "review these with the product team to decide if a taxonomy rule change is warranted."
            )
            with st.expander("View flagged items"):
                for c in prompt_updates:
                    st.markdown(
                        f"- **{c['field_display']}** / {c['country'] or 'any'} / "
                        f"`{c['raw_value']}` → **{c['proposed']}**"
                        + (f" — *{c['reviewer_note']}*" if c['reviewer_note'] else "")
                    )

        st.divider()

        for c in history:
            status_color = "#0D7C5F" if c["status"] == "approved" else "#DC2626"
            status_label = "Approved" if c["status"] == "approved" else "Rejected"

            with st.container(border=True):
                col_status, col_detail = st.columns([1, 5])
                with col_status:
                    st.markdown(
                        f"<span style='color:{status_color};font-weight:bold'>{status_label}</span>",
                        unsafe_allow_html=True,
                    )
                    if c.get("needs_prompt_update"):
                        st.caption("⚑ Prompt update")
                with col_detail:
                    field_badge = (
                        f"<span style='"
                        f"background:rgba(0,107,98,0.1);color:#006B62;font-weight:600;"
                        f"padding:2px 8px;border-radius:20px;font-size:12px;"
                        f"letter-spacing:0.01em'>{c['field_display']}</span>"
                    )
                    st.markdown(
                        f"{field_badge} &nbsp;{c['country'] or '*(any)*'} · "
                        f"`{c['raw_value']}` · "
                        f"~~{c['original']}~~ → **{c['proposed']}**",
                        unsafe_allow_html=True,
                    )
                    meta = f"Submitted by {c['submitted_by'] or 'unknown'} on {c['submitted_at'][:10]}"
                    if c.get("reviewed_at"):
                        meta += f" · Reviewed {c['reviewed_at'][:10]}"
                    st.caption(meta)
                    if c.get("reviewer_note"):
                        st.caption(f"Note: {c['reviewer_note']}")
