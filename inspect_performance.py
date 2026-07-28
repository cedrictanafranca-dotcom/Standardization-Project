import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd

df = pd.read_excel(r"C:\Users\cedric.tanafranca\Downloads\sample_for_live_testing_standardized.xlsx")
print("Shape:", df.shape)
print("Columns:", df.columns.tolist())
print()

std_col = next((c for c in df.columns if "standard" in c.lower()), None)
nr_col = next((c for c in df.columns if "needs" in c.lower()), None)
val_col = next((c for c in df.columns if c.lower() in ("value", "inputtext")), None)

# Overall stats
if std_col:
    print("=== Standardized Value distribution ===")
    print(df[std_col].value_counts().to_string())
    print()

if nr_col:
    flagged = df[nr_col].notna() & (df[nr_col] != "")
    print(f"Flagged for review: {flagged.sum()} / {len(df)} rows ({flagged.mean()*100:.1f}%)")
    print()

# Show all rows — full output for review
print("=== Full output ===")
show_cols = [c for c in df.columns]
with pd.option_context("display.max_rows", 500, "display.max_colwidth", 60, "display.width", 200):
    print(df[show_cols].to_string(index=False))
