import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd

path = r"C:\Users\cedric.tanafranca\Downloads\No translation match found-data-2026-07-23 13_32_21_standardized.xlsx"
df = pd.read_excel(path)

print("Columns:", df.columns.tolist())
print("Shape:", df.shape)
print()

# Find any column that might hold input text
text_col = next((c for c in df.columns if "input" in c.lower()), None)
std_col = next((c for c in df.columns if "standard" in c.lower()), None)
nr_col = next((c for c in df.columns if "needs" in c.lower()), None)
rr_col = next((c for c in df.columns if "reason" in c.lower()), None)

print(f"Text col: {text_col}, Std col: {std_col}, NR col: {nr_col}, Reason col: {rr_col}")
print()

if text_col:
    mask = df[text_col].astype(str).str.contains("Proprietary", case=False, na=False)
    hits = df[mask]
    print(f"Rows with 'Proprietary' in {text_col!r}: {len(hits)}")
    cols = [c for c in [text_col, std_col, nr_col, rr_col] if c]
    with pd.option_context("display.max_colwidth", 80, "display.width", 200):
        print(hits[cols].to_string(index=False))
