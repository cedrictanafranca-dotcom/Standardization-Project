import pandas as pd
from collections import Counter

path = r'C:/Users/cedric.tanafranca/Downloads/No translation match found-data-2026-07-23 13_32_21_standardized (1).xlsx'
df = pd.read_excel(path)

print(f"Total rows: {len(df)}")
print(f"Columns: {list(df.columns)}")
print()

std_col = "Standardized Value"
nr_col = "Needs Review"
rr_col = "Review Reason"

# Confidence breakdown
nr = df[nr_col].fillna("").astype(str)
rr = df[rr_col].fillna("").astype(str)
raw_col = next(c for c in ["inputText", "Value", "value"] if c in df.columns)
raw = df[raw_col].fillna("").astype(str).str.strip()

low = nr.str.startswith("Needs Review") & (raw != "")
med = (~nr.str.startswith("Needs Review")) & (rr != "")
high = (~nr.str.startswith("Needs Review")) & (rr == "") & (raw != "")
blank = raw == ""

print(f"HIGH:   {high.sum()} ({high.sum()/len(df):.0%})")
print(f"MEDIUM: {med.sum()} ({med.sum()/len(df):.0%})")
print(f"LOW:    {low.sum()} ({low.sum()/len(df):.0%})")
print(f"BLANK:  {blank.sum()} ({blank.sum()/len(df):.0%})")
print()

# Standardized value distribution
print("=== Standardized Value counts ===")
for val, count in Counter(df[std_col].fillna("").astype(str)).most_common():
    print(f"  {count:>5}  {val}")
print()

# Flagged rows
flagged = df[low]
if len(flagged):
    ft_col = next((c for c in df.columns if c.lower() == "fieldtype"), None)
    print(f"=== {len(flagged)} Flagged rows ===")
    cols = [c for c in [ft_col, raw_col, std_col, nr_col, rr_col] if c and c in df.columns]
    print(flagged[cols].to_string(index=False))
