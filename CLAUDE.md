# Standardization Project — Context for AI Assistants

## What This Is
An internal Trulioo tool that standardizes raw business data values from Global Gateway (GG) analytics exports into a controlled set of canonical values. Built by Cedric Tanafranca (cedric.tanafranca@trulioo.com). Runs as a Streamlit web app.

**Future state:** Host on AWS (ECS or EC2) as an internal web app for the team. Anthropic API key to be stored in AWS Secrets Manager. IT has confirmed IAM users are not permitted — IAM roles required.

**Run locally:**
```
.venv\Scripts\python.exe -m streamlit run app.py
```

---

## The 10 Fields

Each field has a prompt file in `/prompts/` and an entry in `src/fields.py`.

| Field Key | Display Name | Values | Country-Dependent |
|-----------|-------------|--------|-------------------|
| positions_designations | Positions / Designations | Board Member, Director, Executive Management, Owner / Controller, Authorized Representative, Other / Unclassified | YES |
| business_legal_form | Business Legal Form (BLF) | Sole Proprietorship / Individual Business, Partnership, Company, Non-Profit / Cooperative, Trust / Fund / Scheme, Foreign Entity / Branch, Government / Public Sector Entity, Other / Unclassified | No |
| business_status | Business Status | Active, Inactive, Pending / Insolvency, Other / Unclassified | No |
| psc_beneficiary_type | PSC / Beneficiary Type | Root Business, Owner / Beneficial Owner, Controller, Other / Unclassified | No |
| brn_type | BRN Type | Business Registration Number, Tax ID Number, VAT Number, LEI, Charity Number, Proprietary / Third-party ID, Other / Unclassified | No |
| directors_officers_type | DirectorsOfficers Type | Individual, Business, Other / Unclassified | No |
| business_entity_type | Business Entity Type | Individual, Business, Other / Unclassified | No |
| ownership_relationship_type | OwnershipRelationship Type | Individual, Business, Other / Unclassified | No |
| directors_officers_status | DirectorsOfficers Status | Active, Resigned, Other / Unclassified | No |
| ownership_relationship_status | OwnershipRelationship Status | Active, Inactive, Pending / Insolvency, Other / Unclassified | No |

---

## Architecture

```
app.py                        — Streamlit UI (file upload, results, flagged review, lookup management)
src/
  classifier.py               — Claude API integration, output parsing (HIGH/MEDIUM/LOW confidence)
  standardize_file.py         — Core classification pipeline (dedup, batching, retry, lookup pre-flight)
  analytics_format.py         — Handles GG analytics export format + mixed-field standard format
  fields.py                   — Field registry (prompt path, canonical values, country_dependent flag)
  master_lookup.py            — Loads/manages data/master_lookup.json
  country_lookup.py           — Resolves countryId integers to country name strings
  config.py                   — Paths, API key loading
  run_log.py                  — JSONL run logging
  retry.py                    — Retry with exponential backoff
  build_lookup.py             — One-time script to build master_lookup.json from master Excel file
  apply_resolutions.py        — Applies conflict resolutions to the master file
  corrections.py              — Handles manual corrections from the review UI
prompts/
  positions_designations.md   — Most complex prompt; includes Europe Board Member Rules table
  business_legal_form.md
  business_status.md
  ... (one per field)
data/
  master_lookup.json          — Pre-flight cache of known-good mappings (avoids redundant API calls)
output/                       — Standardized Excel output files written here
```

---

## Input File Formats Supported

1. **GG Analytics export** — columns: `countryId`, `fieldType`, `inputText` (auto-detected)
2. **Multi-tab Excel** — each sheet tab named after a field type; sheet name maps to field registry key
3. **Consolidated single-sheet with Field/Field Type column** — column named "Field", "Field Type", "fieldType", or "field_type" containing field type values per row
4. **Single-field file** — user selects field manually in UI; one raw value column

---

## Classification Pipeline

**Integrated predictive extension (2026-07-30):** After exact lookup and local
artifact filtering, aliases and similarity matches resolve automatically only
when enabled by the source-bound `data/automation_policy.json`. Meaning-changing modifiers remain unresolved and are forced to
human review. Lexical and optional semantic retrieval supply a small set of
approved evidence to Claude; semantic neighbors never classify automatically.
Legacy near-identical automatic predictions are disabled by default until the
golden evaluation validates an acceptance threshold. Strict canonical parsing
and optional independent verification route invalid, conflicting, or
disagreeing decisions to review. See `docs/integrated_predictive_pipeline.md`.
The current offline policy targets 92% precision; see
`docs/automation_calibration_report.md` for measured coverage and limitations.

1. Load file → detect format (analytics / multi-tab / multi-field / single-field)
2. **Pre-flight lookup** — check `data/master_lookup.json` first; known values get HIGH confidence with no API call
3. **System artifact filter** — ALL_CAPS_SNAKE_CASE values (e.g. MASKED_WHOIS_DATA) → catch-all, LOW
4. **Data quality filter** — N/A, null, single chars, "legal form unknown", etc. → catch-all, HIGH (no API call, no review queue noise)
5. **Approved aliases** — safe full aliases resolve locally; uncovered modifiers continue with warnings and mandatory review
6. **Evidence retrieval** — lexical mappings and an optional injected semantic provider return context only
7. **Claude API** — remaining unique values sent in batches (default 100); country-prefixed for positions_designations
8. **Strict output parsing** — canonical labels and confidence contract are validated
9. **Optional verification** — uncertain/high-risk decisions can receive a second independent pass; disagreements require review
10. Write results: Standardized Value, Needs Review, Review Reason columns

---

## Confidence Levels

- **HIGH** — clear match, no review needed
- **MEDIUM** — judgment call; shown in Review Reason column for reference but NOT flagged for mandatory review
- **LOW** — uncertain; flagged in Needs Review column for human action
- **Missing confidence** — treated as LOW (parser couldn't parse the model's output format)

---

## Master Lookup (`data/master_lookup.json`)

Structure:
```json
{
  "field_key": {
    "consistent": { "raw_value": "Standardized Value", ... },
    "by_country": { "country_name": { "raw_value": "Standardized Value", ... } }
  }
}
```

**Critical:** `FieldLookup.get()` checks `by_country` BEFORE `consistent`. Country-specific entries override global ones. This caused a bug where Peru/Indonesia/Norway had `"Officer": "Other / Unclassified"` overriding the correct global mapping — those entries were removed.

Key normalization: `_norm_key()` collapses whitespace but does NOT lowercase. Lookup is case-sensitive.

---

## Key Decisions & Why

**Manager / Operations Manager / etc. → Other / Unclassified**
This is CORRECT per the positions_designations prompt. These are explicitly listed under Other / Unclassified. Do not change this.

**Mock mode only works for positions_designations and business_legal_form**
MockClaudeClient has hand-coded keyword heuristics for these two fields only. All other fields return Other / Unclassified in mock mode. This is intentional — it proves the pipeline works without the API. Real classification requires Live API on.

**Country-dependent classification for positions_designations only**
Only this field has genuine per-country rules (UK/GI/IE/MT CEO/MD → Board Member, etc.). All other fields use value-only dedup — no country context sent to the model.

**"Standardized X" → "Universal X" normalization in output**
The GG platform renamed fields (e.g. "Standardized Position" → "Universal Position"). The output normalizes these in the fieldType column via `_CANONICAL_FIELD_TYPE_NAME` in analytics_format.py.

**ownership_relationship_status reuses business_status prompt**
Intentional — confirmed correct per internal docs. Do not create a separate prompt file for it.

---

## Recent Fixes (as of 2026-07-29)

- **Parser fix (HIGH + extra content):** Model sometimes returns `value | HIGH | Reason: ...` which the parser didn't handle → fell through to non-canonical → Other / Unclassified. Fixed by adding `_OUTPUT_WITH_HIGH_EXTRA` regex in classifier.py.
- **Non-Limited added to lookup:** `data/master_lookup.json` business_legal_form → Other / Unclassified.
- **Field type normalization:** "Standardized Position", "Standardized Designation" etc. in output now show as "Universal Position" etc.
- **Data quality pre-filter:** N/A, null, single chars, "legal form unknown" etc. now resolved locally as HIGH confidence catch-all — no API call, no review queue noise.
- **Positions prompt confidence guidance:** Added "Confidence Guidance" section to positions_designations.md to reduce MEDIUM rate. HIGH should be the default; MEDIUM only for genuinely ambiguous dual-category cases.
- **find_field_col() helper:** Accepts "Field", "Field Type", "fieldType", "field_type" column names — fixes consolidated files that used "Field Type" header.
- **NaN country fix:** country_lookup.py now handles NaN float values without returning "nan" string.
- **Officer mapping fix:** Removed wrong country-specific entries (Peru, Indonesia, Norway) that were overriding the correct global Officer → Executive Management mapping.

---

## Known Remaining Issues / Future Work

- MEDIUM rate on Universal Position still elevated (partially addressed by prompt change — retest needed)
- HIGH confidence Other / Unclassified count was 106 in last production run — parser fix should reduce this significantly; retest needed
- No authentication on the Streamlit app (anyone with the URL can use it — matters once deployed to AWS)
- AWS deployment not yet done (pending IT guidance on IAM roles and compute)

---

## FIELD_TYPE_MAP & STANDARD_FIELD_MAP

Both live in `src/analytics_format.py`. If a new fieldType string appears in GG exports that isn't being recognised, add it to `FIELD_TYPE_MAP` (for analytics format) or `STANDARD_FIELD_MAP` (for standard consolidated format). Keys are lowercased strings; values are field registry keys.

---

## Adding a New Field

1. Add prompt file to `/prompts/`
2. Add `FieldSpec` entry to `src/fields.py` `_SPECS` list
3. Add fieldType string mappings to `FIELD_TYPE_MAP` and `STANDARD_FIELD_MAP` in `src/analytics_format.py`
4. Run `build_lookup.py` if the master Excel file has a sheet for the new field
