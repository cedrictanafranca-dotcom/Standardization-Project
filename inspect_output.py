import pandas as pd

df = pd.read_excel(r'C:\Users\cedric.tanafranca\Downloads\ANALYTICS1-9007 - List of distinct Position and Designations_standardized.xlsx')
print('Columns:', list(df.columns))
print()

# Show distribution of Needs Review column
if 'Needs Review' in df.columns:
    print('Needs Review breakdown:')
    print(df['Needs Review'].fillna('(blank)').value_counts().head(20))
    print()
    print('Rows WITH alternatives (flagged):')
    flagged = df[df['Needs Review'].str.startswith('Needs Review', na=False)]
    print(f'  {len(flagged)} rows flagged')
    print(flagged[['Value', 'Standardized Value', 'Needs Review', 'Review Reason']].head(10).to_string())
else:
    print('No Needs Review column found')

if 'Review Reason' in df.columns:
    print()
    print('Rows WITH reasoning (MEDIUM):')
    reasoned = df[df['Review Reason'].notna() & (df['Review Reason'] != '') & ~df['Needs Review'].str.startswith('Needs Review', na=False)]
    print(f'  {len(reasoned)} rows with reasoning only (MEDIUM)')
