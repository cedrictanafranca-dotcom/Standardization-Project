r"""Step 5.2 — the field registry.

One place mapping field name -> prompt file -> expected standard values.
Adding a new field means adding one FieldSpec here (and dropping its prompt
file in /prompts) — no other code changes needed, per Section 7's build plan.

Standard values are the CONFIRMED lists from the brief's Section 3 table, with
"Other / Unknown" normalized to "Other / Unclassified" everywhere (Section 11:
the customer-facing definitions doc confirms this label fleet-wide, regardless
of what an individual prompt file says).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from classifier import CONFIDENCE_ADDENDUM

CATCH_ALL = "Other / Unclassified"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    display_name: str
    prompt_file: str  # filename within config.PROMPTS_DIR
    standard_values: list[str]
    notes: str = ""
    # True only for fields whose prompt has genuine per-country rules (e.g.
    # Positions/Designations' Europe Board Member Rules table). When True,
    # standardize_file.py dedupes by (country, raw_value) instead of raw
    # value alone, and passes country to the model — otherwise the same raw
    # string always gets one answer regardless of country, which is wrong
    # for a measured ~3% of Positions values (Step 7 finding). Left False by
    # default so the other 9 fields keep the cheaper, correct-for-them
    # value-only dedup and don't pay extra API calls for no benefit.
    country_dependent: bool = False

    @property
    def prompt_path(self):
        return config.PROMPTS_DIR / self.prompt_file

    def load_prompt(self) -> str:
        """The field's verbatim instructions plus the Step 8 confidence
        contract, appended here rather than edited into the prompt file on
        disk — keeps the file itself byte-for-byte as sourced (brief: copy
        verbatim, don't paraphrase or shorten)."""
        base = self.prompt_path.read_text(encoding="utf-8")
        return base.rstrip() + "\n\n" + CONFIDENCE_ADDENDUM


_SPECS = [
    FieldSpec(
        key="business_legal_form",
        display_name="Business Legal Form (BLF)",
        prompt_file="business_legal_form.md",
        standard_values=[
            "Sole Proprietorship / Individual Business", "Partnership", "Company",
            "Non-Profit / Cooperative", "Trust / Fund / Scheme",
            "Foreign Entity / Branch", "Government / Public Sector Entity",
            CATCH_ALL,
        ],
    ),
    FieldSpec(
        key="positions_designations",
        display_name="Positions / Designations",
        prompt_file="positions_designations.md",
        standard_values=[
            "Board Member", "Director", "Executive Management",
            "Owner / Controller", "Authorized Representative", CATCH_ALL,
        ],
        country_dependent=True,
        notes=(
            "Country-dependent: the prompt's embedded Europe Board Member Rules "
            "table and the UK/GI/IE/MT Step 4 rule mean the correct answer for "
            "some raw values (e.g. \"President\", \"CEO\") genuinely differs by "
            "country. Classification is done per (country, raw value) pair, not "
            "raw value alone."
        ),
    ),
    FieldSpec(
        key="business_status",
        display_name="Business Status",
        prompt_file="business_status.md",
        standard_values=["Active", "Inactive", "Pending / Insolvency", CATCH_ALL],
    ),
    FieldSpec(
        key="psc_beneficiary_type",
        display_name="PSC / Beneficiary Type",
        prompt_file="psc_beneficiary_type.md",
        standard_values=["Root Business", "Owner / Beneficial Owner", "Controller", CATCH_ALL],
    ),
    FieldSpec(
        key="brn_type",
        display_name="BRN Type",
        prompt_file="brn_type.md",
        standard_values=[
            "Business Registration Number", "Tax ID Number", "VAT Number", "LEI",
            "Charity Number", "Proprietary / Third-party ID", CATCH_ALL,
        ],
    ),
    FieldSpec(
        key="directors_officers_type",
        display_name="DirectorsOfficers Type",
        prompt_file="directors_officers_type.md",
        standard_values=["Individual", "Business", CATCH_ALL],
    ),
    FieldSpec(
        key="business_entity_type",
        display_name="Business Entity Type",
        prompt_file="business_entity_type.md",
        standard_values=["Individual", "Business", CATCH_ALL],
    ),
    FieldSpec(
        key="ownership_relationship_type",
        display_name="OwnershipRelationship Type",
        prompt_file="ownership_relationship_type.md",
        standard_values=["Individual", "Business", CATCH_ALL],
        notes=(
            "Resolved (brief Section 11, open item #1): confirmed as a genuinely "
            "distinct production field from Business Entity Type, not a duplicate "
            "to collapse — even though the customer-facing definitions doc doesn't "
            "separately document it. Kept as its own field/prompt permanently."
        ),
    ),
    FieldSpec(
        key="directors_officers_status",
        display_name="DirectorsOfficers Status",
        prompt_file="directors_officers_status.md",
        standard_values=["Active", "Resigned", CATCH_ALL],
    ),
    FieldSpec(
        key="ownership_relationship_status",
        display_name="OwnershipRelationship Status",
        prompt_file="business_status.md",  # reuse — see notes
        standard_values=["Active", "Inactive", "Pending / Insolvency", CATCH_ALL],
        notes=(
            "Resolved (brief Section 11): reuses the 4-value Business Status "
            "taxonomy/prompt verbatim. The internal instructions file's standalone "
            "3-value definition for this field (Active/Inactive/Other) is outdated "
            "and intentionally NOT used — do not create a separate prompt file for it."
        ),
    ),
]

FIELDS: dict[str, FieldSpec] = {spec.key: spec for spec in _SPECS}


def get(key: str) -> FieldSpec:
    try:
        return FIELDS[key]
    except KeyError:
        available = ", ".join(sorted(FIELDS))
        raise KeyError(f"Unknown field {key!r}. Available: {available}") from None


def list_fields() -> list[FieldSpec]:
    return list(FIELDS.values())
