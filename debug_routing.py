import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd
from analytics_format import (
    is_analytics_format,
    is_multi_field_standard,
    resolve_standard_field,
    STANDARD_FIELD_MAP,
)

df = pd.read_excel(r"C:\Users\cedric.tanafranca\Desktop\Standardization Project\data\sample_for_live_testing.xlsx")

print("Columns:", df.columns.tolist())

field_col = next((c for c in df.columns if str(c).strip().lower() == "field"), None)
print("Field column detected:", field_col)

if field_col:
    vals = df[field_col].dropna().unique().tolist()
    print("\nUnique Field values:")
    for v in vals:
        resolved = resolve_standard_field(str(v))
        print(f"  '{v}'  ->  {resolved}")

print("\nis_analytics_format:", is_analytics_format(df))
print("is_multi_field_standard:", is_multi_field_standard(df))

print("\nSTANDARD_FIELD_MAP keys (sample):")
for k in list(STANDARD_FIELD_MAP.keys())[:6]:
    print(f"  '{k}'")
