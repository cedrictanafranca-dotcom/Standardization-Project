import pandas as pd

df = pd.read_excel(r"C:\Users\cedric.tanafranca\Downloads\test_100rows_standardized.xlsx")
print("Shape:", df.shape)
print("Columns:", df.columns.tolist())
print()

with pd.option_context("display.max_rows", 100, "display.max_colwidth", 60, "display.width", 200):
    print(df.to_string(index=False))
