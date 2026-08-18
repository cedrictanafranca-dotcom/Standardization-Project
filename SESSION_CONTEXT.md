# Standardization Tool — Session Context (2026-08-14 to 2026-08-17)

## What This Session Covered

Live debugging, feature work, and GG mapping table analysis across two sessions.

---

## Code Changes Made

### 1. Case-Insensitive Lookup (`src/master_lookup.py`, `src/standardize_file.py`)

**Problem:** Lookup was case-sensitive. `"INAPTA"` in the lookup would not match `"inapta"` from a file.

**Fix:**
- `_norm()` in `master_lookup.py` now casesfolds: `" ".join(str(s).casefold().split())`
- `_norm_key()` in `standardize_file.py` now casesfolds
- `load_lookup()` normalizes all keys on load from JSON
- `merge_api_results()` casesfolds new keys before writing
- `_normalize_lookup_data()` helper added
- `master_lookup.json` normalized in-place — all keys now lowercase

**Applies to:** All 10 fields. Accent stripping does NOT happen — only case folding.

---

### 2. Deduplication of Output Rows (`src/analytics_format.py`, `standardize_page.py`)

**Problem:** Output had duplicate rows. Two root causes:

1. **countryId collapse:** Multiple `countryId` values resolve to the same country name (e.g., US state-level IDs → "United States"). Dedup was on raw `countryId`, not resolved country name.
2. **fieldType variants:** GG analytics exports contain multiple `fieldType` strings for the same logical field (e.g., `Standardized Designation`, `Standardized Position`, and `Universal Position` all map to `positions_designations`). The dedup used the **raw** fieldType string, so rows with different spellings weren't collapsed. After dedup, fieldType normalization made them identical — producing visible duplicates (e.g., 233 rows → 139 unique).

**Fixes applied (all currently in place):**

| Location | What | Dedup key |
|----------|------|-----------|
| `src/analytics_format.py` — `process_analytics_df()` | Resolve countryId first; normalize fieldType before dedup | `(Country, fieldType, norm_inputText)` |
| `src/analytics_format.py` — `process_standard_multi_field_df()` | Normalize field column before dedup | `(field, country, norm_value)` |
| `standardize_page.py` — single-field path | Dedup before calling `standardize_dataframe` | `(country, norm_value)` |
| `standardize_page.py` — `_dedup_result()` | **Safety net** on ALL results before display/export | `(country_col, field_col, norm_value_col)` |

**`STANDARD_FIELD_MAP` additions:** `"universal business legal form"` and `"universal business status"` added so `resolve_standard_field()` works after canonical names are applied.

**Key rule:** Different countries with same value = NOT duplicates. Only same-country + same-field + same-normalized-value rows are collapsed. Volume/count columns are summed before collapsing.

**Important:** After code changes, must Ctrl+C Streamlit and rerun. Also delete `src/__pycache__` and root `__pycache__` to avoid stale bytecode.

---

### 3. Partner → PSC/Beneficiary Type (`data/master_lookup.json`)

Added `"partner": "Owner / Beneficial Owner"` to the `consistent` section of `psc_beneficiary_type`. Previously it fell through to Claude (LOW confidence) for countries not in the by_country lookup. Country-specific entries still override the global consistent entry.

---

### 4. Field Type Badge in Review UI (`pages/2_Review_Corrections.py`)

Field type now shows as a green pill/badge (`#1F6E5C`) in both Pending and History tabs of the Review Corrections page.

---

### 5. Jira Ticket Section — All Run Types (`standardize_page.py`)

Ticket content section previously only showed for single-field runs. Now shows for all run types — one text area per field type, plus a combined download button.

---

## Running the App

```powershell
cd "C:\Users\cedric.tanafranca\Desktop\Standardization Project"
.venv\Scripts\python.exe -m streamlit run app.py
```

Runs at http://localhost:8501. Browser refresh does NOT restart — must Ctrl+C and rerun.

---

## Key Architecture Reminders

### Lookup Priority (per row)
1. `reviewed_by_country` — highest
2. `reviewed_consistent`
3. `by_country`
4. `consistent` — lowest

### Normalization
- `_norm()` / `_norm_key()`: whitespace collapse + casefold only
- `_similarity_key()`: + accent stripping + punctuation removal (fuzzy only)

### File Format Detection Order
1. Analytics: has `countryId`, `fieldType`, `inputText` → `process_analytics_df()`
2. Multi-field standard: has `Field`/`fieldType` column → `process_standard_multi_field_df()`
3. Single-field: everything else → `standardize_dataframe()`

---

## Pending Decisions

### Inapta (Brazil) — Business Status
Currently mapped to `"Pending / Insolvency"`. It's a Receita Federal CNPJ non-compliance status (unfit due to non-filing) — arguably closer to `"Inactive"` than insolvency. No change made — needs Cedric's decision.

---

## GG Mapping Table Analysis (2026-08-17)

**File analyzed:** `C:\Users\cedric.tanafranca\Downloads\Universal fields GG - Sheet2 (1).csv`

**Output files on Desktop:**
- `GG_exploded.xlsx` — full table with every raw value on its own row (6,851 rows)
- `GG_analysis.txt` — full breakdown by field: global, multi-country, single-country, conflicts

**Scale:** 6,851 raw value entries, 155 countries, 4 universal field types.

---

### Streamlining Opportunities

| Action | Impact |
|--------|--------|
| Make `"active"` a global Business Status rule | Consistent in 149/153 countries |
| Make `"corporation"` a global BLF rule | 99 countries |
| Make `"sole proprietorship / individual business"` + `"proprietorship"` global | 61–64 countries |
| Fix Global row errors for cooperative/nonprofit/foundation → Non-Profit/Cooperative | GG has them as Government/Public Sector — wrong |
| Resolve `"partner"` in PSC/Beneficiary → global Owner/Beneficial Owner | 26 countries currently split |
| Clean up 1,527 single-country Universal Position values | Many are multi-role combos |

---

### GG Errors Confirmed Against Prompt Rules

#### Universal Position
| Raw Value | GG Mapping | Correct Mapping | Notes |
|-----------|-----------|-----------------|-------|
| `"secretary"` in Belgium/France | Other/Unclassified | Executive Management | Secretary is explicitly EM in prompt |
| `"manager"` in Germany/Italy | Executive Management | Other/Unclassified | Manager explicitly listed as Other/Unclassified in prompt |
| `"managing director"` in Belgium/India/Italy/Japan/Portugal | Board Member | Executive Management | Step 4 override only applies to UK/GI/IE/MT |
| `"partner"` in 21 countries | Controller | Owner/Beneficial Owner | Prompt explicitly lists Partner under Owner/BO |
| `"subsidiary"` in 7 countries | Company | Foreign Entity/Branch | Prompt explicitly maps Subsidiary to Foreign Entity/Branch |
| `"ordinary"` in Cyprus/HK/Singapore | Other/Unclassified | Owner/Beneficial Owner | Ordinary shares = ownership |
| `"person with significant control"` in France | Owner/Beneficial Owner | Controller | PSC = control per prompt |

#### Universal Business Legal Form — Global Row Errors
| Raw Value | GG Global Mapping | Correct Mapping |
|-----------|------------------|-----------------|
| `"cooperative"` | Government/Public Sector | Non-Profit/Cooperative |
| `"nonprofit organization"` | Government/Public Sector | Non-Profit/Cooperative |
| `"foundation"` | Government/Public Sector | Non-Profit/Cooperative |

#### Confirmed Correct Country Rules (not errors)
- `"managing director"` / `"ceo"` in **UK/GI/IE/MT** → Board Member ✅ (Step 4)
- `"administrator"` in **France/Portugal** → Board Member ✅ (Administrateur/Administrador = board title in those jurisdictions)
- `"director"` in **Ireland/Cyprus/Malta** → Board Member ✅ (Board Filter applies per country rules)
- `"director"` in **India** → Board Member in GG but **not confirmed** by prompt — still an open question

#### Open Question
`"director"` in UK/US: GG maps to Board Member, our tool has Director as its own separate category. Need team decision on whether Director should ever be used or always collapse into Board Member/Executive Management per jurisdiction.

---

### Additional Smaller Opportunities (lower priority)
- `"secretary"` in Belgium/France → fix to Executive Management
- `"manager"` in Germany/Italy → fix to Other/Unclassified
- `"ceo"` in UK → Board Member already correct
- `"trustee"` in Argentina → GG says Executive Management, Board Member more appropriate
- `"sa"` in Korea → GG says Other/Unclassified, should be Company
- Multi-role combo strings (hundreds of entries like `"president,secretary,treasurer"`) → could be replaced with pattern rules
- `"ordinary"` in PSC/Beneficiary → fix Cyprus/HK/Singapore to Owner/Beneficial Owner
