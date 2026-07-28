import pandas as pd

files = {
    "No candidate found": r"C:\Users\cedric.tanafranca\Downloads\No candidate found-data-2026-07-23 13_32_29.csv",
    "No translation match": r"C:\Users\cedric.tanafranca\Downloads\No translation match found-data-2026-07-23 13_32_21.csv",
}

for label, path in files.items():
    print(f"\n{'='*60}")
    print(label)
    print('='*60)
    df = pd.read_csv(path)
    print(f"Shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
    print(f"\nUnique fieldTypes: {sorted(df['fieldType'].dropna().unique().tolist()) if 'fieldType' in df.columns else 'N/A'}")
    print(f"\nFirst 5 rows:")
    print(df.head(5).to_string(index=False))
