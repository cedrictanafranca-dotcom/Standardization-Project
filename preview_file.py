import pandas as pd

path = r'C:\Users\cedric.tanafranca\Downloads\ANALYTICS1-9007 - List of distinct Position and Designations.xlsx'
df = pd.read_excel(path)
print('Shape:', df.shape)
print('Columns:', list(df.columns))
print()
print(df.head(20).to_string())
