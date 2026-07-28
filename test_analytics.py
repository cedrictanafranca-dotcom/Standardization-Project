"""Quick smoke test for the new analytics format modules.
Run: .venv/Scripts/python.exe test_analytics.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd
from country_lookup import resolve_country_id
from analytics_format import is_analytics_format, summarize_field_types, resolve_field_type

# --- country_lookup ---
assert resolve_country_id(224) == "United Kingdom", resolve_country_id(224)
assert resolve_country_id(1) == "Australia", resolve_country_id(1)
assert resolve_country_id(-1) == "Global", resolve_country_id(-1)
assert resolve_country_id(0) == "Unknown", resolve_country_id(0)
assert resolve_country_id(999) == "Unknown (ID: 999)", resolve_country_id(999)
assert resolve_country_id("56") == "Germany", resolve_country_id("56")
print("country_lookup: OK")

# --- resolve_field_type ---
assert resolve_field_type("Standardized Designation") == "positions_designations"
assert resolve_field_type("Standardized Position") == "positions_designations"
assert resolve_field_type("Business Legal Form") == "business_legal_form"
assert resolve_field_type("Universal Business Legal Form") == "business_legal_form"
assert resolve_field_type("Business Status") == "business_status"
assert resolve_field_type("Something Unknown") is None
print("resolve_field_type: OK")

# --- is_analytics_format ---
df_analytics = pd.DataFrame({"countryId": [1], "fieldType": ["Business Legal Form"], "inputText": ["Ltd"]})
df_standard = pd.DataFrame({"Country": ["UK"], "Value": ["Ltd"]})
assert is_analytics_format(df_analytics) is True
assert is_analytics_format(df_standard) is False
print("is_analytics_format: OK")

# --- summarize_field_types ---
df = pd.DataFrame({
    "countryId": [1, 2, 3, 4],
    "fieldType": ["Standardized Designation", "Business Legal Form", "Standardized Designation", "Unknown Type X"],
    "inputText": ["Director", "Ltd", "CEO", "Foo"],
})
summary = summarize_field_types(df)
# Should have 3 entries (2 unique known + 1 unknown)
assert len(summary) == 3, summary
known = [s for s in summary if s["known"]]
unknown = [s for s in summary if not s["known"]]
assert len(known) == 2, known
assert len(unknown) == 1, unknown
assert unknown[0]["field_type"] == "Unknown Type X"
# Standardized Designation should have 2 rows
sd = next(s for s in summary if s["field_type"] == "Standardized Designation")
assert sd["row_count"] == 2, sd
assert sd["display_name"] == "Positions / Designations", sd
print("summarize_field_types: OK")

print("\nAll checks passed.")
