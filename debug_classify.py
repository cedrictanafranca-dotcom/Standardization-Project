"""
Diagnose why specific positions/designations values are returning Other/Unclassified.
Run: .venv\Scripts\python.exe debug_classify.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd
import config
from master_lookup import load_lookup
from standardize_file import _norm_key
from classifier import RealClaudeClient, build_user_message
import fields

# ── 1. Check what the master lookup returns ──────────────────────────────────
print("=" * 60)
print("1. MASTER LOOKUP CHECK")
print("=" * 60)

lookup = load_lookup()
pd_lookup = lookup.get("positions_designations")

test_values = [
    ("Vice President", "United States"),
    ("vice president", "United States"),
    ("Chairman", "Australia"),
    ("chairman", "Australia"),
    ("Chief Executive Officer", "Canada"),
    ("CEO", "United States"),
    ("Administrator", "Argentina"),
]

if pd_lookup is None:
    print("  ERROR: positions_designations not found in lookup at all!")
else:
    print(f"  Consistent entries: {len(pd_lookup.consistent)}")
    print(f"  Country entries: {pd_lookup.country_entry_count}")
    print()
    for raw, country in test_values:
        result = pd_lookup.get(raw, country)
        norm_raw = _norm_key(raw)
        in_consistent = norm_raw in pd_lookup.consistent
        print(f"  get({raw!r}, {country!r}) -> {result!r}  (key '{norm_raw}' in consistent: {in_consistent})")

# ── 2. Check what's actually in the sample file ──────────────────────────────
print()
print("=" * 60)
print("2. SAMPLE FILE — positions_designations values")
print("=" * 60)

try:
    df = pd.read_excel("data/sample_for_live_testing.xlsx")
    field_col = next((c for c in df.columns if str(c).strip().lower() == "field"), None)
    val_col = next((c for c in df.columns if str(c).strip().lower() == "value"), None)
    country_col = next((c for c in df.columns if str(c).strip().lower() == "country"), None)
    print(f"  Columns: {df.columns.tolist()}")
    print(f"  field_col={field_col!r}  val_col={val_col!r}  country_col={country_col!r}")
    print()

    if field_col and val_col:
        pos_mask = df[field_col].astype(str).str.strip().str.lower() == "positions_designations"
        pos_df = df[pos_mask]
        print(f"  positions_designations rows: {len(pos_df)}")
        print()
        for _, row in pos_df.head(20).iterrows():
            raw = str(row[val_col]) if val_col else "?"
            country = str(row[country_col]) if country_col else ""
            norm = _norm_key(raw)
            if pd_lookup:
                hit = pd_lookup.get(norm, country)
            else:
                hit = None
            print(f"  raw={raw!r:40s}  country={country!r:20s}  lookup={hit!r}")
except Exception as e:
    print(f"  Could not read sample file: {e}")

# ── 3. Live API test — send 5 obvious values with the real prompt ────────────
print()
print("=" * 60)
print("3. LIVE API TEST (5 values, real Claude)")
print("=" * 60)

if not config.has_real_api_key():
    print("  No API key configured — skipping live test.")
else:
    spec = fields.get("positions_designations")
    system_prompt = spec.load_prompt()
    print(f"  Prompt length: {len(system_prompt)} chars")
    print(f"  Prompt ends with (last 120 chars):")
    print(f"  ...{system_prompt[-120:]!r}")
    print()

    test_vals = ["Chairman", "Vice President", "Chief Executive Officer", "Director", "Shareholder"]
    user_msg = build_user_message(test_vals)
    print("  Sending to Claude:")
    for i, v in enumerate(test_vals, 1):
        print(f"    {i}. {v}")
    print()

    try:
        client = RealClaudeClient()
        raw_response = client.complete(system_prompt, user_msg)
        print("  Raw Claude response:")
        print("  " + "\n  ".join(raw_response.splitlines()))
    except Exception as e:
        print(f"  API call failed: {e}")
