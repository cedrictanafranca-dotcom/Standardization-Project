import pandas as pd

src = r"C:\Users\cedric.tanafranca\Downloads\ANALYTICS1-9007 - List of distinct Position and Designations.xlsx"
df = pd.read_excel(src)
print("Full shape:", df.shape)
print("Columns:", df.columns.tolist())
print(df.head(3).to_string())

out = r"C:\Users\cedric.tanafranca\Downloads\test_100rows.xlsx"
df.head(100).to_excel(out, index=False)
print(f"\nSaved 100 rows to: {out}")
