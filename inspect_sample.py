import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd

df = pd.read_excel(r"C:\Users\cedric.tanafranca\Desktop\Standardization Project\data\sample_for_live_testing.xlsx")
print("Shape:", df.shape)
print("Columns:", df.columns.tolist())
print()
print(df.head(10).to_string())
