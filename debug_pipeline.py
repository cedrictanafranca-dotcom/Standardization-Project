"""
Runs the exact same pipeline the web app uses and shows results step by step.
No Streamlit involved — if this works correctly, the bug is Streamlit-specific.
Run: .venv\Scripts\python.exe debug_pipeline.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd
from analytics_format import is_analytics_format, is_multi_field_standard, process_standard_multi_field_df
from standardize_file import detect_value_column, detect_country_column, STANDARDIZED_COLUMN, REVIEW_REASON_COLUMN
from master_lookup import load_lookup
from standardize_file import _norm_key

DATA_FILE = "data/sample_for_live_testing.xlsx"

# ── Step 1: read the file ──────────────────────────────────────────────────
df = pd.read_excel(DATA_FILE)
print(f"Columns : {df.columns.tolist()}")
print(f"Shape   : {df.shape}")
print()

# ── Step 2: column detection (same as app) ────────────────────────────────
is_analytics = is_analytics_format(df)
is_multi     = is_multi_field_standard(df)

try:
    value_col = detect_value_column(df)
except ValueError as e:
    value_col = None
    print(f"  detect_value_column FAILED: {e}")

country_col = detect_country_column(df)

field_col = next((c for c in df.columns if str(c).strip().lower() == "field"), None)

print(f"is_analytics_format    : {is_analytics}")
print(f"is_multi_field_standard: {is_multi}")
print(f"value_col  : {value_col!r}")
print(f"country_col: {country_col!r}")
print(f"field_col  : {field_col!r}")
print()

# ── Step 3: show actual raw values per field type + lookup hits ────────────
if field_col and value_col:
    lookup = load_lookup()
    pd_lookup = lookup.get("positions_designations")

    print("─" * 70)
    print("RAW VALUES PER FIELD TYPE (first 10 each) + lookup result")
    print("─" * 70)
    for ft, grp in df.groupby(field_col, dropna=False):
        print(f"\n  [{ft}] ({len(grp)} rows)")
        import fields as field_registry
        from analytics_format import resolve_standard_field
        fk = resolve_standard_field(str(ft))
        fk_lookup = lookup.get(fk) if fk else None
        for _, row in grp.head(10).iterrows():
            raw = str(row[value_col]) if value_col else "?"
            country = str(row[country_col]) if country_col else ""
            norm = _norm_key(raw)
            hit = fk_lookup.get(norm, country) if fk_lookup else None
            destination = f"LOOKUP -> {hit!r}" if hit else "-> API"
            print(f"    {raw!r:40s}  [{country}]  {destination}")

# ── Step 4: run the pipeline in MOCK mode (no API cost) to check routing ──
print()
print("─" * 70)
print("PIPELINE RUN (SIMULATION MODE — checks routing, not real classifications)")
print("─" * 70)

if not is_multi:
    print("  ERROR: is_multi_field_standard is False — app will use single-field BLF!")
    print("  This is why everything gets Other/Unclassified.")
else:
    result_df, analytics_stats = process_standard_multi_field_df(
        df,
        value_col=value_col,
        country_col=country_col,
        use_live=False,   # mock mode — no API cost
        batch_size=100,
    )

    for fs in analytics_stats.field_summaries:
        s = fs.get("stats")
        if s:
            print(f"  {fs['field_type']:40s}  rows={fs['row_count']}  "
                  f"lookup_hits={s.lookup_hits}  api_batches={s.batches}  "
                  f"flagged={s.flagged_count}")
        else:
            print(f"  {fs['field_type']:40s}  rows={fs['row_count']}  known={fs['known']}")

    # Show first 15 positions/designations rows
    if field_col:
        pd_mask = result_df[field_col].astype(str).str.strip().str.lower() == "positions_designations"
        pd_rows = result_df[pd_mask]
        print(f"\n  First 15 positions/designations results (MOCK):")
        expected_col = next((c for c in result_df.columns if "expected" in c.lower()), None)
        for _, row in pd_rows.head(15).iterrows():
            raw = row[value_col]
            std = row[STANDARDIZED_COLUMN]
            exp = row[expected_col] if expected_col else "?"
            match = "✓" if str(std).strip() == str(exp).strip() else "✗"
            print(f"    {match} {raw!r:35s} -> {std!r:30s}  (expected: {exp!r})")

print("\nDone.")
