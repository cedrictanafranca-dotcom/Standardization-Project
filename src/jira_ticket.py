r"""Section 5 (item 8) — ready-to-paste Jira ticket content for the
engineering handoff. Generates the title + description text an analyst pastes
directly into a new Jira ticket — NOT a live Jira API integration (that's
explicitly deferred to Phase 2 per Section 6, pending IT/security approval on
API token use).

Template matches the real ticket format already in use for this handoff
(e.g. KYB-7558): a title naming the field, a spreadsheet-reference bullet, a
country-list bullet, and a fixed "Steps" section describing how the exported
columns map onto the master "GG" mapping table's columns (Input/Value/Type).
The Steps text is boilerplate — the same three sentences regardless of field,
since they describe a fixed process convention, not run-specific data.

Run (after a normal standardize_file.py run has produced an output file):
    .venv\Scripts\python.exe src\jira_ticket.py --field business_legal_form --data data\sample_blf.xlsx
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

import pandas as pd

import config
import fields

# Fixed process convention (see module docstring) — not run-specific.
STEPS_BOILERPLATE = [
    'The column "{raw_col}" should map out to the "Input" column on GG.',
    'The column "Standardized Value" should map out to the "Value" column on GG.',
    'The column "Field" should map out to the "Type" column on GG.',
]

_COUNTRY_COLUMN_CANDIDATES = ["country", "countries"]
_TRAILING_ABBREVIATION = re.compile(r"\s*\([A-Z]+\)\s*$")


def _ticket_field_name(display_name: str) -> str:
    """Strip a trailing " (ABBREV)" for ticket text — the registry keeps the
    abbreviation for the UI dropdown, but the real ticket convention (e.g.
    KYB-7558) just says "Business Legal Form", not "Business Legal Form (BLF)"."""
    return _TRAILING_ABBREVIATION.sub("", display_name)


def find_countries(df: pd.DataFrame) -> list[str]:
    """Unique, sorted country values, if a country-like column exists."""
    normalized = {str(c).strip().lower(): c for c in df.columns}
    for cand in _COUNTRY_COLUMN_CANDIDATES:
        if cand in normalized:
            col = normalized[cand]
            values = sorted({str(v).strip() for v in df[col].dropna() if str(v).strip()})
            return values
    return []


def build_ticket_text(
    field_display_name: str,
    raw_col: str,
    countries: list[str],
    output_filename: str,
) -> str:
    """Ready-to-paste title + description text for one field's run."""
    name = _ticket_field_name(field_display_name)
    title = f"Add Standardization mapping to content standardization table - {name}"
    country_list = ", ".join(countries) if countries else "(no country column found in source file)"

    lines = [
        f"Title: {title}",
        "",
        "Description:",
        "I have a table of values I want to add to the field content standardization "
        "table, could you please use this spreadsheet as reference:",
        "",
        f" - {name} -> {output_filename}  (attach this file to the ticket)",
        "",
        "The following countries are included in this ticket:",
        "",
        f" - {name}: {country_list}",
        "",
        "Steps:",
        "",
    ]
    for step in STEPS_BOILERPLATE:
        lines.append(f" - {step.format(raw_col=raw_col)}")

    return "\n".join(lines)


def main() -> int:
    # Lazy import: avoids a circular import since standardize_file.py imports
    # build_ticket_text()/find_countries() from this module at top level.
    from standardize_file import DEFAULT_DATA_FILE, detect_value_column, read_table

    parser = argparse.ArgumentParser(description="Generate ready-to-paste Jira ticket content")
    parser.add_argument("--field", required=True, choices=sorted(fields.FIELDS))
    parser.add_argument("--data", type=Path, default=None,
                         help=f"defaults to {DEFAULT_DATA_FILE} if omitted")
    parser.add_argument("--column", default=None, help="raw-value column (else auto-detect)")
    args = parser.parse_args()

    spec = fields.get(args.field)
    data_path = args.data or DEFAULT_DATA_FILE
    if not data_path.exists():
        print(f"Data file not found: {data_path}")
        return 1

    df = read_table(data_path)
    try:
        raw_col = detect_value_column(df, args.column)
    except ValueError as exc:
        print(f"[!] {exc}")
        return 1

    countries = find_countries(df)
    output_filename = f"{data_path.stem}_standardized.xlsx"
    output_path = config.OUTPUT_DIR / output_filename
    if not output_path.exists():
        print(f"NOTE: {output_path} doesn't exist yet — run standardize_file.py "
              "first to produce it. Generating ticket text anyway.")

    text = build_ticket_text(spec.display_name, raw_col, countries, output_filename)
    print(text)

    out_txt = config.OUTPUT_DIR / f"{data_path.stem}_jira_ticket.txt"
    out_txt.write_text(text, encoding="utf-8")
    print(f"\nSaved to: {out_txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
