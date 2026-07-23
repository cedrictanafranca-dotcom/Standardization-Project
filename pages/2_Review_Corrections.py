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

st.set_page_config(page_title="Review Corrections — Standardization Tool", layout="wide")

st.markdown("""
<style>
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
div[data-testid="stAlert"] {
    background-color: #DCE9DD !important;
    border-left-color: #1F6E5C !important;
}
.correction-card {
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
    background: #FAFAFA;
}
</style>
""", unsafe_allow_html=True)

if Path("assets/trulioo_logo.png").exists():
    st.logo("assets/trulioo_logo.png")

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Demo")
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

# ── Page header ───────────────────────────────────────────────────────────────

pending = cq.get_pending()
history = cq.get_history()

st.title("Correction Review Queue")
st.caption(
    "Corrections submitted by reviewers appear here. Approve to write the value "
    "into the master lookup (no API call for that value in future runs). "
    "Reject to discard. Flag for prompt update if the pattern recurs enough to "
    "warrant a rule change in the taxonomy prompt."
)

tab_pending, tab_history = st.tabs([
    f"Pending ({len(pending)})",
    f"History ({len(history)})",
])

# ── Pending tab ───────────────────────────────────────────────────────────────

with tab_pending:
    if not pending:
        st.info(
            "No corrections pending. Reviewers submit corrections from the main page "
            "after running a file. Use **Load demo data** in the sidebar to see a "
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
                    st.markdown(
                        f"**{c['field_display']}**  ·  "
                        f"{c['country'] or '*(no country)*'}"
                        + demo_badge
                    )
                with col_submitted:
                    submitted_date = c["submitted_at"][:10]
                    st.caption(f"Submitted {submitted_date} by {c['submitted_by'] or 'unknown'}")

                # Before → After
                col_val, col_arrow, col_proposed = st.columns([3, 1, 3])
                with col_val:
                    st.markdown(f"**Raw value:** `{c['raw_value']}`")
                    st.markdown(
                        f"<span style='color:#888'>Original:</span> "
                        f"**{c['original']}**",
                        unsafe_allow_html=True,
                    )
                with col_arrow:
                    st.markdown("<div style='text-align:center;font-size:24px;padding-top:20px'>→</div>", unsafe_allow_html=True)
                with col_proposed:
                    st.markdown(f"&nbsp;")
                    st.markdown(
                        f"<span style='color:#1F6E5C'>Proposed:</span> "
                        f"**{c['proposed']}**",
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
            status_color = "#1F6E5C" if c["status"] == "approved" else "#cc3333"
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
                    st.markdown(
                        f"**{c['field_display']}** · {c['country'] or '*(any)*'} · "
                        f"`{c['raw_value']}` · "
                        f"~~{c['original']}~~ → **{c['proposed']}**"
                    )
                    meta = f"Submitted by {c['submitted_by'] or 'unknown'} on {c['submitted_at'][:10]}"
                    if c.get("reviewed_at"):
                        meta += f" · Reviewed {c['reviewed_at'][:10]}"
                    st.caption(meta)
                    if c.get("reviewer_note"):
                        st.caption(f"Note: {c['reviewer_note']}")
