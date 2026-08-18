"""Beginner-friendly operating guide and field reference."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import fields
from user_guidance import (
    CLASSIFICATION_RULES,
    FIELD_GUIDANCE,
    GUIDANCE_LAST_UPDATED,
    parse_country_rules,
    validate_guidance,
)
from ui_theme import apply_brand_theme

apply_brand_theme()

st.title("Help & Field Guide")
st.caption(f"Everything needed to use and understand the tool. Updated {GUIDANCE_LAST_UPDATED}.")
st.info(
    "Start with Quick Start if this is your first time. Use Field Guide when you want to "
    "understand a result or check how a mapping was decided."
)

specs = fields.list_fields()
issues = validate_guidance(specs)
if issues:
    st.error("The help content is out of sync with the classifier. Contact the application owner.")
    with st.expander("Technical details"):
        for issue in issues:
            st.write(f"- {issue}")
    st.stop()


def _load_reviewed_rows(field_key: str) -> list[tuple[str, str, str]]:
    overrides_path = ROOT / "data" / "reviewed_overrides.json"
    try:
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
        selected = overrides.get("fields", {}).get(field_key, {})
    except (OSError, json.JSONDecodeError):
        return []

    rows: list[tuple[str, str, str]] = []
    for raw_value, final_value in selected.get("consistent", {}).items():
        rows.append(("All countries", raw_value, final_value))
    for country, mappings in selected.get("by_country", {}).items():
        for raw_value, final_value in mappings.items():
            rows.append((country, raw_value, final_value))
    return sorted(rows)


quick_tab, field_tab, questions_tab = st.tabs([
    "Quick Start",
    "Field Guide",
    "Common Questions",
])

with quick_tab:
    st.header("Four simple steps")
    step_columns = st.columns(4)
    steps = [
        ("1", "Upload", "Add the approved CSV or Excel file you want to standardize."),
        ("2", "Run", "Select Run and keep the browser open while the file is processed."),
        ("3", "Review", "Read the Mapping Reason and resolve any rows that are flagged."),
        ("4", "Download", "Download the standardized file and confirm its rows and columns."),
    ]
    for column, (number, title, description) in zip(step_columns, steps):
        with column:
            with st.container(border=True):
                st.markdown(f"### {number}. {title}")
                st.write(description)

    st.success(
        "If no review dropdown appears, the run did not contain any rows requiring a manual decision. "
        "You can proceed to download."
    )

    with st.expander("File formats"):
        st.markdown(
            "- **Analytics export:** contains `countryId`, `fieldType`, and `inputText`. The field is detected automatically.\n"
            "- **Simple value list:** contains a column such as `Value`, `Raw Value`, or `Input`. You may need to choose the field."
        )

    with st.expander("Output columns"):
        st.markdown(
            "**Standardized Value** — the final category selected by the tool or reviewer.\n\n"
            "**Mapping Reason** — a plain-language explanation of why the category was selected.\n\n"
            "**Needs Review** — identifies a decision that a person should check.\n\n"
            "**Review Reason** — provides additional uncertainty or validation details."
        )

    with st.expander("Advanced settings"):
        st.markdown(
            "- **Use real Claude API:** turn this on for actual classifications; leave it off only for a demonstration.\n"
            "- **Batch size:** leave this at 100 unless the support team advises otherwise.\n"
            "- **Minimum value count:** set this to 1 when every row must be included. A higher number excludes less-common values.\n"
            "- **Field override:** use this only when a simple file does not identify its field type."
        )

with field_tab:
    st.header("Understand a field")
    st.write("Choose a field once to see what its results mean and how its mappings are decided.")

    labels = {spec.display_name: spec for spec in specs}
    selected_label = st.selectbox("Choose a field", options=list(labels))
    selected = labels[selected_label]
    guidance = FIELD_GUIDANCE[selected.key]
    rule = CLASSIFICATION_RULES[selected.key]

    st.subheader(selected.display_name)
    st.write(guidance["summary"])
    if guidance.get("note"):
        st.warning(guidance["note"])

    meanings_tab, decisions_tab, examples_tab = st.tabs([
        "What the results mean",
        "How mappings are decided",
        "Approved examples",
    ])

    with meanings_tab:
        result_search = st.text_input(
            "Search these results",
            placeholder="Example: director, company, inactive",
        ).strip().casefold()
        shown = 0
        for category in selected.standard_values:
            detail = guidance["categories"][category]
            searchable = " ".join([category, detail["meaning"], *detail["examples"]]).casefold()
            if result_search and result_search not in searchable:
                continue
            shown += 1
            with st.container(border=True):
                st.markdown(f"### {category}")
                st.write(detail["meaning"])
                st.markdown("**Examples:** " + "; ".join(detail["examples"]))
        if shown == 0:
            st.info("No results match that search. Try a shorter word.")

    with decisions_tab:
        st.markdown("### General decision process")
        for number, step in enumerate(rule["steps"], start=1):
            st.markdown(f"**{number}.** {step}")

        st.markdown("### When more than one result fits")
        st.write(rule["priority"])

        notes = rule.get("notes", [])
        if notes:
            st.markdown("### Important exceptions")
            for note in notes:
                st.markdown(f"- {note}")

        if selected.country_dependent:
            st.markdown("### Country-specific rules")
            st.write(
                "Local legal titles can change the correct result. A country rule takes priority "
                "over the general rule."
            )
            country_rules = parse_country_rules(selected.prompt_path.read_text(encoding="utf-8"))
            if country_rules:
                country_names = [item["country"] for item in country_rules]
                chosen_country = st.selectbox("Choose a country", country_names)
                country_rule = next(item for item in country_rules if item["country"] == chosen_country)
                with st.container(border=True):
                    st.markdown(f"#### {country_rule['country']} ({country_rule['code']})")
                    st.markdown("**Board Member titles**")
                    st.write(country_rule["board_terms"])
                    st.markdown("**Management titles that are not board membership**")
                    st.write(country_rule["management_terms"])
                    st.markdown("**Why this country is treated differently**")
                    st.write(country_rule["nuance"])
                if country_rule["code"] in ("GB", "GI", "IE", "MT"):
                    st.warning(
                        "In this jurisdiction, CEO, Chief Executive Officer, "
                        "and Managing Director map to Board Member."
                    )
            else:
                st.warning("No country-specific rules could be displayed. Contact the application owner.")
        else:
            st.caption("This field uses the same general rules in every country.")

    with examples_tab:
        st.write(
            "These exact values were previously reviewed and approved. They do not automatically "
            "create a broad rule for every similar value."
        )
        reviewed_rows = _load_reviewed_rows(selected.key)
        if not reviewed_rows:
            st.info("There are no saved approved examples for this field yet.")
        else:
            example_search = st.text_input(
                "Search approved examples",
                placeholder="Search by country, source value, or result",
            ).strip().casefold()
            matches = [
                row for row in reviewed_rows
                if not example_search or example_search in " ".join(row).casefold()
            ]
            for country, raw_value, final_value in matches:
                with st.container(border=True):
                    st.markdown(f"**{raw_value}** → **{final_value}**")
                    st.caption(f"Applies to: {country}")
            if not matches:
                st.info("No approved examples match that search.")

with questions_tab:
    st.header("Common questions")
    with st.expander("Why are fewer rows in the result?"):
        st.write("Check Minimum value count. Set it to 1 to include every row.")
    with st.expander("Why is there no review dropdown?"):
        st.write("The dropdown appears only when at least one row is flagged for review.")
    with st.expander("Why was a field skipped?"):
        st.write("The field name may not match a supported field. Use Field Guide to check the available fields.")
    with st.expander("What should I do if I disagree with a mapping?"):
        st.write(
            "Choose the correct result during the flagged review. If the file is already complete, "
            "submit the value through the correction workflow."
        )
    with st.expander("What should I send when asking for help?"):
        st.write(
            "Send the file name, field type, error message, and a screenshot. "
            "Never send API keys or passwords."
        )

st.divider()
st.caption(
    "The detailed AI instructions are protected and cannot be edited here. Use Review Corrections for "
    "an exact mapping change, or flag a correction for a broader rule update. Follow company data-handling requirements."
)
