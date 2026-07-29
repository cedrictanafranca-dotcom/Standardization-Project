import pandas as pd

path = r'C:\Users\cedric.tanafranca\Downloads\No translation match found-data-2026-07-28 14_46_29_standardized.xlsx'
df = pd.read_excel(path)

print(f'Rows: {len(df)}')
print(f'Columns: {list(df.columns)}')

std_col = 'Standardized Value'
nr_col = 'Needs Review'
rr_col = 'Review Reason'

def get_conf(row):
    nr = str(row[nr_col]) if pd.notna(row[nr_col]) else ''
    rr = str(row[rr_col]) if pd.notna(row[rr_col]) else ''
    if nr.startswith('Needs Review'):
        return 'LOW'
    elif rr:
        return 'MEDIUM'
    return 'HIGH'

df['conf'] = df.apply(get_conf, axis=1)

print(f'\nOVERALL:')
print(df['conf'].value_counts().to_string())
print(f'\nStandardized Value breakdown:')
print(df[std_col].value_counts().head(20).to_string())

# Per field type if available
ft_col = next((c for c in df.columns if str(c).strip().lower() in ('fieldtype', 'field type', 'field')), None)
if ft_col:
    print(f'\nBY FIELD TYPE:')
    for ft, grp in df.groupby(ft_col):
        total = len(grp)
        high = (grp['conf'] == 'HIGH').sum()
        med = (grp['conf'] == 'MEDIUM').sum()
        low = (grp['conf'] == 'LOW').sum()
        other_unclass = (grp[std_col] == 'Other / Unclassified').sum()
        print(f'  {str(ft)[:45]:<45} total={total:>4} HIGH={high:>3} MED={med:>3} LOW={low:>3} Other/Unclass={other_unclass:>3}')

# LOW confidence sample
print(f'\nLOW CONFIDENCE SAMPLE (first 15):')
low_rows = df[df['conf'] == 'LOW']
input_col = next((c for c in df.columns if str(c).strip().lower() in ('inputtext', 'input', 'value')), None)
if input_col:
    cols = [c for c in [ft_col, 'Country', input_col, std_col, rr_col] if c and c in df.columns]
    print(low_rows[cols].head(15).to_string())

# Other/Unclassified that are HIGH confidence (potential errors)
print(f'\nHIGH confidence OTHER/UNCLASSIFIED (potential misclassifications, first 20):')
suspect = df[(df['conf'] == 'HIGH') & (df[std_col] == 'Other / Unclassified')]
print(f'Count: {len(suspect)}')
if input_col:
    cols = [c for c in [ft_col, 'Country', input_col] if c and c in df.columns]
    print(suspect[cols].head(20).to_string())
