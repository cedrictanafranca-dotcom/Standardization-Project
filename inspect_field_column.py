"""Check what distinct values appear in the Field column across your files.
Run: .venv/Scripts/python.exe inspect_field_column.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd

files = [
    r"C:\Users\cedric.tanafranca\Downloads\ANALYTICS1-9007 - List of distinct Position and Designations.xlsx",
    r"C:\Users\cedric.tanafranca\Downloads\test_100rows.xlsx",
]

for f in files:
    p = Path(f)
    if not p.exists():
        print(f"Not found: {p.name}")
        continue
    df = pd.read_excel(p)
    field_col = next((c for c in df.columns if str(c).strip().lower() == "field"), None)
    if field_col is None:
        print(f"{p.name}: no 'Field' column found. Columns: {list(df.columns)}")
        continue
    vals = df[field_col].dropna().unique().tolist()
    print(f"{p.name}:")
    for v in sorted(vals):
        count = (df[field_col] == v).sum()
        print(f"  '{v}'  ({count} rows)")
    print()
