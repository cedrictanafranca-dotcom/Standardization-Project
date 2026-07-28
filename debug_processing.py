import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd
from analytics_format import process_standard_multi_field_df, resolve_standard_field
from standardize_file import detect_value_column, detect_country_column, STANDARDIZED_COLUMN, REVIEW_REASON_COLUMN
from classifier import MockClaudeClient
import fields

df = pd.read_excel(r"C:\Users\cedric.tanafranca\Desktop\Standardization Project\data\sample_for_live_testing.xlsx")

value_col = detect_value_column(df)
country_col = detect_country_column(df)
field_col = next(c for c in df.columns if str(c).strip().lower() == "field")

print(f"value_col: {value_col!r}")
print(f"country_col: {country_col!r}")
print(f"field_col: {field_col!r}")
print()

# Test each group manually
for ft, group_idx in df.groupby(field_col, dropna=False).groups.items():
    field_key = resolve_standard_field(str(ft))
    spec = fields.get(field_key) if field_key else None
    print(f"Field type: {ft!r} -> key: {field_key!r} -> prompt file: {spec.prompt_file if spec else 'NONE'}")
    if spec:
        prompt = spec.load_prompt()
        # Show first 80 chars of prompt to confirm it's the right one
        print(f"  Prompt starts: {prompt[:80].strip()!r}")
    print(f"  Rows: {len(group_idx)}")
    print()
