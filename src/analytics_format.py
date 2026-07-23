"""Detect and process the Global Gateway analytics export CSV format.

Analytics exports have three key columns that distinguish them from the
standard raw-value files:
  - countryId   : integer Trulioo country enum value
  - fieldType   : string like "Standardized Designation", "Business Legal Form"
  - inputText   : the raw value to classify

A single file can contain multiple fieldTypes (mixed-field file), so processing
splits by fieldType, classifies each group with the correct prompt, and
recombines in original row order.

Business context on inputText sources:
  "No candidate found"     — no translation candidates are configured at all
                             for that country + fieldType combination.
  "No translation match"   — candidates exist but none matched the inputText.
Both situations need classification; the distinction is only context for the
analyst reviewing the output.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import fields
from classifier import MockClaudeClient, RealClaudeClient
from country_lookup import resolve_country_id
from standardize_file import (
    NEEDS_REVIEW_COLUMN,
    REVIEW_REASON_COLUMN,
    STANDARDIZED_COLUMN,
    standardize_dataframe,
)

# Required columns (checked case-insensitively).
_REQUIRED_COLS = {"countryid", "fieldtype", "inputtext"}

# Standard format "Field" column value (lowercased) → field registry key.
# Used when a regular file has a "Field" column with mixed field types.
STANDARD_FIELD_MAP: dict[str, str] = {
    # Human-readable column values
    "designation": "positions_designations",
    "position": "positions_designations",
    "business legal form": "business_legal_form",
    "business status": "business_status",
    "brn type": "brn_type",
    "psc beneficiary type": "psc_beneficiary_type",
    "directors officers type": "directors_officers_type",
    "business entity type": "business_entity_type",
    "ownership relationship type": "ownership_relationship_type",
    "directors officers status": "directors_officers_status",
    "ownership relationship status": "ownership_relationship_status",
    # Field key strings used directly in some files
    "positions_designations": "positions_designations",
    "business_legal_form": "business_legal_form",
    "business_status": "business_status",
    "brn_type": "brn_type",
    "psc_beneficiary_type": "psc_beneficiary_type",
    "directors_officers_type": "directors_officers_type",
    "business_entity_type": "business_entity_type",
    "ownership_relationship_type": "ownership_relationship_type",
    "directors_officers_status": "directors_officers_status",
    "ownership_relationship_status": "ownership_relationship_status",
}

# fieldType string (lowercased) → field registry key.
# Extend this dict when new fieldTypes are added to the platform.
FIELD_TYPE_MAP: dict[str, str] = {
    "standardized designation": "positions_designations",
    "standardized position": "positions_designations",
    "business legal form": "business_legal_form",
    "universal business legal form": "business_legal_form",
    "business status": "business_status",
    "psc beneficiary type": "psc_beneficiary_type",
    "brn type": "brn_type",
    "directors officers type": "directors_officers_type",
    "business entity type": "business_entity_type",
    "ownership relationship type": "ownership_relationship_type",
    "directors officers status": "directors_officers_status",
    "ownership relationship status": "ownership_relationship_status",
}

# Synthetic column name added during processing (not in original data).
RESOLVED_COUNTRY_COLUMN = "Country"


def is_analytics_format(df: pd.DataFrame) -> bool:
    """Return True if df looks like a Global Gateway analytics export."""
    cols_lower = {str(c).lower().strip() for c in df.columns}
    return _REQUIRED_COLS.issubset(cols_lower)


def _find_col(df: pd.DataFrame, name_lower: str) -> str:
    """Return the actual column name whose lowercased/stripped form matches name_lower."""
    for c in df.columns:
        if str(c).lower().strip() == name_lower:
            return c
    raise KeyError(f"Column matching {name_lower!r} not found in {list(df.columns)}")


def resolve_field_type(field_type: str) -> str | None:
    """Map a fieldType string to a field registry key, or None if unknown."""
    return FIELD_TYPE_MAP.get(str(field_type).strip().lower())


def summarize_field_types(df: pd.DataFrame) -> list[dict]:
    """Return a list of dicts describing each unique fieldType in the file.

    Each dict has keys:
      field_type   — original string from the column
      field_key    — matched registry key, or None
      display_name — human-readable taxonomy name from the registry, or None
      row_count    — how many rows have this fieldType
      known        — bool, True if a classifier is available
    """
    ft_col = _find_col(df, "fieldtype")
    summary = []
    for ft, group in df.groupby(ft_col, dropna=False):
        fk = resolve_field_type(str(ft))
        display = fields.get(fk).display_name if fk is not None else None
        summary.append({
            "field_type": ft,
            "field_key": fk,
            "display_name": display,
            "row_count": len(group),
            "known": fk is not None,
        })
    return sorted(summary, key=lambda x: x["row_count"], reverse=True)


@dataclass
class AnalyticsStats:
    """Aggregated stats for a multi-field analytics run."""
    total_rows: int
    field_summaries: list[dict]  # one per fieldType processed
    unknown_field_types: list[str]  # fieldTypes with no registered classifier


def process_analytics_df(
    df: pd.DataFrame,
    use_live: bool,
    batch_size: int,
) -> tuple[pd.DataFrame, AnalyticsStats]:
    """Classify an analytics-format DataFrame.

    Steps:
      1. Resolve countryId → Country name (adds RESOLVED_COUNTRY_COLUMN).
      2. Split by fieldType.
      3. For each known fieldType: run standardize_dataframe with the matching
         field spec. Country-dependent fields (Positions/Designations) get the
         resolved country column passed in automatically.
      4. For unknown fieldTypes: fill result columns with a placeholder.
      5. Recombine in original row order.

    Returns the enriched DataFrame (original columns + Standardized Value /
    Needs Review / Review Reason) and an AnalyticsStats summary.
    """
    ft_col = _find_col(df, "fieldtype")
    input_col = _find_col(df, "inputtext")

    result = df.copy()

    # 1. Resolve country IDs.
    country_id_col = _find_col(df, "countryid")
    result[RESOLVED_COUNTRY_COLUMN] = result[country_id_col].apply(resolve_country_id)

    # Pre-populate result columns so every row gets a value.
    result[STANDARDIZED_COLUMN] = ""
    result[NEEDS_REVIEW_COLUMN] = ""
    result[REVIEW_REASON_COLUMN] = ""

    unknown_types: list[str] = []
    field_summaries: list[dict] = []

    real_client = RealClaudeClient() if use_live else None

    for ft, group_idx in result.groupby(ft_col, dropna=False).groups.items():
        field_key = resolve_field_type(str(ft))

        if field_key is None:
            unknown_types.append(str(ft))
            result.loc[group_idx, STANDARDIZED_COLUMN] = "Unknown field type"
            result.loc[group_idx, NEEDS_REVIEW_COLUMN] = (
                f"{NEEDS_REVIEW_COLUMN}: no classifier for field type {ft!r}"
            )
            field_summaries.append({
                "field_type": ft,
                "field_key": None,
                "row_count": len(group_idx),
                "known": False,
                "stats": None,
            })
            continue

        spec = fields.get(field_key)
        system_prompt = spec.load_prompt()
        blank_fill = spec.standard_values[-1]

        if use_live:
            client = real_client
        else:
            client = MockClaudeClient(field_key=field_key)

        group_df = result.loc[group_idx].copy()

        sub_result, stats = standardize_dataframe(
            group_df,
            column=input_col,
            system_prompt=system_prompt,
            client=client,
            batch_size=batch_size,
            blank_fill=blank_fill,
            country_dependent=spec.country_dependent,
            country_column=RESOLVED_COUNTRY_COLUMN if spec.country_dependent else None,
            field_key=field_key,
        )

        # Write results back into the correct rows of the full DataFrame.
        result.loc[group_idx, STANDARDIZED_COLUMN] = sub_result[STANDARDIZED_COLUMN].values
        result.loc[group_idx, NEEDS_REVIEW_COLUMN] = sub_result[NEEDS_REVIEW_COLUMN].values
        result.loc[group_idx, REVIEW_REASON_COLUMN] = sub_result[REVIEW_REASON_COLUMN].values

        field_summaries.append({
            "field_type": ft,
            "field_key": field_key,
            "display_name": spec.display_name,
            "row_count": len(group_idx),
            "known": True,
            "stats": stats,
        })

    analytics_stats = AnalyticsStats(
        total_rows=len(df),
        field_summaries=field_summaries,
        unknown_field_types=unknown_types,
    )
    return result, analytics_stats


# ---------------------------------------------------------------------------
# Standard format with mixed Field column
# ---------------------------------------------------------------------------

def resolve_standard_field(field_val: str) -> str | None:
    """Map a standard-format Field column value to a field registry key, or None."""
    return STANDARD_FIELD_MAP.get(str(field_val).strip().lower())


def is_multi_field_standard(df: pd.DataFrame) -> bool:
    """Return True if df has a 'Field' column containing at least one known field type.

    This catches standard-format files (Country / Value / Field / ...) where
    the Field column mixes types like 'Designation', 'Position',
    'Business Legal Form', etc. — each group needs a different classifier.
    """
    field_col = next(
        (c for c in df.columns if str(c).strip().lower() == "field"), None
    )
    if field_col is None:
        return False
    return any(
        resolve_standard_field(str(v)) is not None
        for v in df[field_col].dropna().unique()
    )


def process_standard_multi_field_df(
    df: pd.DataFrame,
    value_col: str,
    country_col: str | None,
    use_live: bool,
    batch_size: int,
) -> tuple[pd.DataFrame, AnalyticsStats]:
    """Classify a standard-format DataFrame that has a mixed 'Field' column.

    Splits by the Field column value, classifies each group with the matching
    field spec, and recombines in original row order — identical logic to
    process_analytics_df but without the countryId resolution step.
    """
    field_col = next(c for c in df.columns if str(c).strip().lower() == "field")

    result = df.copy()
    result[STANDARDIZED_COLUMN] = ""
    result[NEEDS_REVIEW_COLUMN] = ""
    result[REVIEW_REASON_COLUMN] = ""

    unknown_types: list[str] = []
    field_summaries: list[dict] = []
    real_client = RealClaudeClient() if use_live else None

    for ft, group_idx in result.groupby(field_col, dropna=False).groups.items():
        field_key = resolve_standard_field(str(ft))

        if field_key is None:
            unknown_types.append(str(ft))
            result.loc[group_idx, STANDARDIZED_COLUMN] = "Unknown field type"
            result.loc[group_idx, NEEDS_REVIEW_COLUMN] = (
                f"{NEEDS_REVIEW_COLUMN}: no classifier for field type {ft!r}"
            )
            field_summaries.append({
                "field_type": ft,
                "field_key": None,
                "row_count": len(group_idx),
                "known": False,
                "stats": None,
            })
            continue

        spec = fields.get(field_key)
        system_prompt = spec.load_prompt()
        blank_fill = spec.standard_values[-1]
        client = real_client if use_live else MockClaudeClient(field_key=field_key)

        group_df = result.loc[group_idx].copy()
        effective_country_col = country_col if spec.country_dependent else None

        sub_result, stats = standardize_dataframe(
            group_df,
            column=value_col,
            system_prompt=system_prompt,
            client=client,
            batch_size=batch_size,
            blank_fill=blank_fill,
            country_dependent=spec.country_dependent,
            country_column=effective_country_col,
            field_key=field_key,
        )

        result.loc[group_idx, STANDARDIZED_COLUMN] = sub_result[STANDARDIZED_COLUMN].values
        result.loc[group_idx, NEEDS_REVIEW_COLUMN] = sub_result[NEEDS_REVIEW_COLUMN].values
        result.loc[group_idx, REVIEW_REASON_COLUMN] = sub_result[REVIEW_REASON_COLUMN].values

        field_summaries.append({
            "field_type": ft,
            "field_key": field_key,
            "display_name": spec.display_name,
            "row_count": len(group_idx),
            "known": True,
            "stats": stats,
        })

    return result, AnalyticsStats(
        total_rows=len(df),
        field_summaries=field_summaries,
        unknown_field_types=unknown_types,
    )
