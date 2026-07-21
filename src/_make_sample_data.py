"""Utility: generate a small Positions/Designations sample file for testing.

This is a stand-in until you drop in a real raw-value export. It writes ~30
rows with a `country` and a `value` column, mixing clean titles, multilingual
titles, compound/multi-title strings, and messy/blank entries — the kinds of
inputs Step 2 needs to survive.

Run:
    .venv\\Scripts\\python.exe src\\_make_sample_data.py
"""

from __future__ import annotations

import pandas as pd

import config

SAMPLE_ROWS = [
    ("US", "Chief Executive Officer"),
    ("US", "CFO"),
    ("US", "President"),
    ("GB", "Managing Director"),
    ("GB", "Company Secretary"),
    ("GB", "Non-Executive Director"),
    ("GB", "Chairman of the Board"),
    ("NL", "Bestuurder"),
    ("NL", "Commissaris"),
    ("DE", "Geschäftsführer"),
    ("DE", "Aufsichtsratsmitglied"),
    ("DE", "Prokurist"),
    ("FR", "Administrateur"),
    ("FR", "Directeur Général"),
    ("IT", "Amministratore Delegato"),
    ("IT", "Consigliere"),
    ("SK", "Konateľ"),
    ("US", "Beneficial Owner"),
    ("US", "Shareholder"),
    ("US", "Managing Partner"),
    ("US", "Ultimate Parent"),
    ("US", "Legal Representative"),
    ("US", "Authorized Signatory"),
    ("US", "Liquidator"),
    ("US", "General Manager"),
    ("US", "Operations Manager"),
    ("US", "Director"),
    ("US", "ceo, cfo, secretary"),
    ("US", "President,Secretary,Director"),
    ("US", ""),
    ("US", "xyz123"),
    ("US", "Treasurer"),
]


# A messier, Format-A-style file for testing Step 3 specifically: extra
# passthrough columns, the raw column NOT named "value", intentional duplicate
# raw values across rows/countries, and blank/whitespace-only entries.
# Columns loosely mirror Section 8 Format A (country, datasourcename, field,
# Inputs, volume, pct_value_returned).
FULL_ROWS = [
    # country, datasourcename, field, Inputs, volume, pct_value_returned
    ("US", "SourceA", "position", "CEO", 1200, 0.98),
    ("GB", "SourceA", "position", "CEO", 300, 0.95),          # dup raw, diff country
    ("DE", "SourceB", "position", "Geschäftsführer", 540, 0.90),
    ("US", "SourceA", "position", "CEO", 80, 0.99),           # dup raw again
    ("US", "SourceB", "position", "Director", 640, 0.97),
    ("GB", "SourceA", "position", "Director", 210, 0.96),     # dup raw
    ("US", "SourceA", "position", "Beneficial Owner", 150, 0.93),
    ("NL", "SourceC", "position", "Bestuurder", 90, 0.88),
    ("US", "SourceA", "position", "Manager", 60, 0.80),
    ("US", "SourceB", "position", "", 0, 0.0),                # blank
    ("US", "SourceB", "position", "   ", 0, 0.0),             # whitespace-only
    ("US", "SourceA", "position", "Liquidator", 12, 0.70),
    ("FR", "SourceC", "position", "Administrateur", 45, 0.85),
    ("US", "SourceA", "position", "Chairman of the Board", 33, 0.91),
    ("US", "SourceA", "position", "Director", 25, 0.94),      # dup raw
    ("US", "SourceB", "position", "Treasurer", 18, 0.89),
]


# Step 5.4 — a SECOND field's sample data (Business Legal Form), to prove the
# registry/pipeline generalizes rather than only working for Positions. Header
# is "Raw Value" (with a space) — yet another synonym per Section 9 — to keep
# exercising flexible column detection too. Includes a duplicate and a blank.
BLF_ROWS = [
    ("US", "LLC"),
    ("GB", "Ltd"),
    ("DE", "GmbH"),
    ("US", "Sole Trader"),
    ("GB", "LLP"),
    ("NL", "Stichting"),
    ("US", "Trust"),
    ("FR", "Branch"),
    ("US", "Government Agency"),
    ("US", "Inc"),
    ("US", "LLC"),          # duplicate raw value
    ("US", ""),             # blank
    ("US", "asdkjhqwe"),    # nonsense -> catch-all
]


def main() -> None:
    df = pd.DataFrame(SAMPLE_ROWS, columns=["country", "value"])
    out_path = config.DATA_DIR / "sample_positions.xlsx"
    df.to_excel(out_path, index=False)
    print(f"Wrote {len(df)} rows -> {out_path}")

    full = pd.DataFrame(
        FULL_ROWS,
        columns=["country", "datasourcename", "field", "Inputs", "volume", "pct_value_returned"],
    )
    full_path = config.DATA_DIR / "sample_positions_full.xlsx"
    full.to_excel(full_path, index=False)
    print(f"Wrote {len(full)} rows -> {full_path}  "
          f"(raw column 'Inputs', with duplicates + blanks for Step 3 testing)")

    blf = pd.DataFrame(BLF_ROWS, columns=["country", "Raw Value"])
    blf_path = config.DATA_DIR / "sample_blf.xlsx"
    blf.to_excel(blf_path, index=False)
    print(f"Wrote {len(blf)} rows -> {blf_path}  "
          f"(raw column 'Raw Value', second field for Step 5.4 generalization test)")


if __name__ == "__main__":
    main()
