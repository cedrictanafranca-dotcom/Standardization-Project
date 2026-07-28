import pandas as pd
from pathlib import Path

df = pd.read_excel(r"C:\Users\cedric.tanafranca\Downloads\No candidate found-data-2026-07-23 13_32_29_standardized.xlsx")
print(f"Shape: {df.shape}")
print(f"Columns: {df.columns.tolist()}")
print()

# Show flagged rows only
nr_col = "Needs Review"
std_col = "Standardized Value"
if nr_col in df.columns:
    flagged = df[df[nr_col].notna() & (df[nr_col] != "")]
    print(f"Flagged rows: {len(flagged)}")
    print()
    print(flagged[["fieldType", "inputText", std_col, nr_col, "Review Reason"]].to_string(index=False))
    print()
    print("--- All unique Standardized Values in flagged rows ---")
    print(sorted(flagged[std_col].dropna().unique().tolist()))
