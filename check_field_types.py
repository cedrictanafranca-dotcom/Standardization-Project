import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
import pandas as pd
from analytics_format import resolve_field_type

files = {
    "No candidate found": r"C:\Users\cedric.tanafranca\Downloads\No candidate found-data-2026-07-23 13_32_29.csv",
    "No translation match": r"C:\Users\cedric.tanafranca\Downloads\No translation match found-data-2026-07-23 13_32_21.csv",
}

for label, path in files.items():
    print(f"\n{'='*60}")
    print(label)
    print('='*60)
    df = pd.read_csv(path)
    for ft in sorted(df['fieldType'].dropna().unique()):
        resolved = resolve_field_type(ft)
        status = f"→ {resolved}" if resolved else "✗ NOT MAPPED"
        print(f"  {ft!r:45s} {status}")
