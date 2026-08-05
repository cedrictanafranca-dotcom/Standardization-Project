"""Generate developer-ready standardization constructor lines.

The generator never decides a mapping. It formats finalized classifier output
and marks rows that are not safe to turn into code. Constructor names are kept
in one small configuration map so additional field formats can be confirmed
without redesigning the export workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from analytics_format import resolve_field_type
from standardize_file import ERROR_FILL, NEEDS_REVIEW_COLUMN, STANDARDIZED_COLUMN


@dataclass(frozen=True)
class ScriptTemplate:
    class_name: str
    value_delimiter: str = "~"
    basis: str = "Inferred — confirm with developers"


# BusinessTypeStandardization comes directly from the user's format example.
# The remaining class names are intentionally straightforward inferences for a
# working demo and are labeled as provisional in every export. The mappings in
# the example are not used anywhere in this module.
SCRIPT_TEMPLATES: dict[str, ScriptTemplate] = {
    "business_legal_form": ScriptTemplate("BusinessLegalFormStandardization"),
    "positions_designations": ScriptTemplate("PositionStandardization"),
    "business_status": ScriptTemplate("BusinessStatusStandardization"),
    "psc_beneficiary_type": ScriptTemplate("BeneficiaryTypeStandardization"),
    "brn_type": ScriptTemplate("BusinessRegistrationNumberTypeStandardization"),
    "directors_officers_type": ScriptTemplate("DirectorsOfficersTypeStandardization"),
    "business_entity_type": ScriptTemplate(
        "BusinessTypeStandardization",
        basis="Example provided — field association still provisional",
    ),
    "ownership_relationship_type": ScriptTemplate("OwnershipRelationshipTypeStandardization"),
    "directors_officers_status": ScriptTemplate("DirectorsOfficersStatusStandardization"),
    "ownership_relationship_status": ScriptTemplate("OwnershipRelationshipStatusStandardization"),
}


# ISO-style enum codes needed by current reviewed/test data. Unknown country
# names are reported for confirmation instead of being guessed.
COUNTRY_ENUM_CODES: dict[str, str] = {
    "australia": "AU",
    "austria": "AT",
    "belgium": "BE",
    "brazil": "BR",
    "bulgaria": "BG",
    "canada": "CA",
    "croatia": "HR",
    "cyprus": "CY",
    "czech republic": "CZ",
    "czechia": "CZ",
    "denmark": "DK",
    "estonia": "EE",
    "finland": "FI",
    "france": "FR",
    "germany": "DE",
    "gibraltar": "GI",
    "greece": "GR",
    "hong kong": "HK",
    "hungary": "HU",
    "iceland": "IS",
    "indonesia": "ID",
    "ireland": "IE",
    "italy": "IT",
    "latvia": "LV",
    "liechtenstein": "LI",
    "lithuania": "LT",
    "luxembourg": "LU",
    "malta": "MT",
    "monaco": "MC",
    "netherlands": "NL",
    "norway": "NO",
    "poland": "PL",
    "portugal": "PT",
    "romania": "RO",
    "slovakia": "SK",
    "slovenia": "SI",
    "spain": "ES",
    "sweden": "SE",
    "switzerland": "CH",
    "taiwan": "TW",
    "taiwan, province of china": "TW",
    "united kingdom": "GB",
    "united states": "US",
    "united states of america": "US",
}


EXPORT_COLUMNS = [
    "Field",
    "Country",
    "Country Enum",
    "Raw Value",
    "Final Mapping",
    "Script Class",
    "Template Basis",
    "Status",
    "Generated Script",
]


def _clean(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split())


def country_enum_code(country: str) -> str | None:
    """Return a safe enum member code, or None when confirmation is needed."""
    cleaned = _clean(country)
    if len(cleaned) == 2 and cleaned.isalpha():
        return cleaned.upper()
    return COUNTRY_ENUM_CODES.get(cleaned.casefold())


def _field_key(row: pd.Series, fixed_field_key: str | None, field_col: str | None) -> str:
    if fixed_field_key:
        return fixed_field_key
    if field_col and field_col in row.index:
        return resolve_field_type(_clean(row.get(field_col))) or ""
    return ""


def _script_line(template: ScriptTemplate, enum_code: str, final_value: str, raw_value: str) -> str:
    delimiter = template.value_delimiter
    return (
        f"new {template.class_name}(CountryEnum.{enum_code},"
        f"{delimiter}{final_value}{delimiter},{delimiter}{raw_value}{delimiter}),"
    )


def build_developer_export(
    result_df: pd.DataFrame,
    *,
    raw_col: str | None,
    country_col: str | None,
    fixed_field_key: str | None = None,
    field_col: str | None = None,
) -> pd.DataFrame:
    """Return one validated developer-export row per unique final mapping."""
    if not raw_col or raw_col not in result_df.columns:
        return pd.DataFrame(columns=EXPORT_COLUMNS)

    records: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for _, row in result_df.iterrows():
        raw_value = _clean(row.get(raw_col))
        final_value = _clean(row.get(STANDARDIZED_COLUMN))
        country = _clean(row.get(country_col)) if country_col and country_col in row.index else ""
        field_key = _field_key(row, fixed_field_key, field_col)
        enum_code = country_enum_code(country)
        template = SCRIPT_TEMPLATES.get(field_key)
        needs_review = _clean(row.get(NEEDS_REVIEW_COLUMN))

        dedupe_key = (field_key, enum_code or country.casefold(), final_value, raw_value)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        status = "Ready — provisional template"
        if not raw_value:
            status = "Excluded: blank raw value"
        elif not final_value or final_value == ERROR_FILL or final_value.startswith("Unknown field type"):
            status = "Excluded: unresolved mapping"
        elif needs_review:
            status = "Excluded: review not confirmed"
        elif not field_key:
            status = "Template needed: unknown field"
        elif template is None:
            status = "Template needed for this field"
        elif not country:
            status = "Country enum needed: country is blank"
        elif enum_code is None:
            status = "Country enum needed: country is not configured"
        elif template.value_delimiter in raw_value or template.value_delimiter in final_value:
            status = f"Excluded: value contains {template.value_delimiter!r} delimiter"

        script = ""
        if status.startswith("Ready") and template is not None and enum_code is not None:
            script = _script_line(template, enum_code, final_value, raw_value)

        records.append({
            "Field": field_key or "Unknown",
            "Country": country or "(blank)",
            "Country Enum": f"CountryEnum.{enum_code}" if enum_code else "",
            "Raw Value": raw_value,
            "Final Mapping": final_value,
            "Script Class": template.class_name if template else "",
            "Template Basis": template.basis if template else "Not configured",
            "Status": status,
            "Generated Script": script,
        })

    return pd.DataFrame(records, columns=EXPORT_COLUMNS)


def ready_script_text(export_df: pd.DataFrame) -> str:
    """Return paste-ready lines only; validation/status stays in the workbook."""
    if export_df.empty or "Status" not in export_df.columns:
        return ""
    lines: Iterable[str] = export_df.loc[
        export_df["Status"].astype(str).str.startswith("Ready"), "Generated Script"
    ].astype(str)
    return "\n".join(line for line in lines if line)
