"""Creates data/sample_flagged_review_test.xlsx for testing the inline flagged review UI."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
import pandas as pd

rows = [
    # positions_designations — keyword matches → HIGH (lookup hit or mock keyword)
    {"Country": "United States", "Field": "positions_designations", "Value": "Chairman"},
    {"Country": "United States", "Field": "positions_designations", "Value": "Vice President"},
    {"Country": "United States", "Field": "positions_designations", "Value": "Director"},
    {"Country": "Canada",        "Field": "positions_designations", "Value": "CEO"},
    # positions_designations — no keyword match → LOW (flagged for review)
    {"Country": "United States", "Field": "positions_designations", "Value": "Tax Advisor"},
    {"Country": "Australia",     "Field": "positions_designations", "Value": "Trustee"},
    {"Country": "Germany",       "Field": "positions_designations", "Value": "Head of Compliance"},
    # business_legal_form — keyword matches → HIGH
    {"Country": "Germany",   "Field": "business_legal_form", "Value": "GmbH"},
    {"Country": "Germany",   "Field": "business_legal_form", "Value": "AG"},
    {"Country": "Australia", "Field": "business_legal_form", "Value": "Pty Ltd"},
    # business_legal_form — no keyword match → LOW (flagged for review)
    {"Country": "Germany",   "Field": "business_legal_form", "Value": "Freiberufler"},
    {"Country": "Australia", "Field": "business_legal_form", "Value": "Uniting Church Body"},
]

df = pd.DataFrame(rows)
out = Path("data/sample_flagged_review_test.xlsx")
out.parent.mkdir(exist_ok=True)
df.to_excel(out, index=False)
print(f"Created: {out}  ({len(df)} rows)")
print(df.to_string(index=False))
