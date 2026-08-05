# Standardization Tool

A tool for KYC/AML field-content standardization: takes a file of raw entity/
relationship values in, returns standardized (canonical) values out, using the
classification logic already refined in Claude Projects. Built solo with Claude
Code. See the Master Project Brief for full context.

Current state: **working end-to-end pilot undergoing accuracy validation and
production hardening**. The Streamlit application supports multiple input
formats, exact and predictive lookup, retrieval-assisted Claude
classification, review/correction workflows, and downloadable Excel results.
See `CLAUDE.md` for the detailed architecture and current known issues.

The first user-reviewed validation pass was completed on 2026-08-04. All 24
AI-disagreement cases and 20 additional agreement cases were reviewed. The
review confirmed 18 tool corrections and six prompt-policy clarifications.
Those decisions are now enforced through `data/reviewed_overrides.json`, an
exact-match layer that takes priority over historical mappings without entering
similarity calibration. A fresh unseen validation sample is the next accuracy
milestone.

The accuracy-first predictive components are now integrated on
`codex/predictive-integration`. Exact lookups and explicitly approved aliases
may resolve automatically; modifier cases and conflicting evidence are forced
to review; semantic retrieval supplies evidence only. No external embedding
provider is selected or enabled. See `docs/integrated_predictive_pipeline.md`
for routing, safeguards, offline test commands, and remaining decisions.
The current 92%-target deterministic calibration and prioritized ambiguity
review are summarized in `docs/automation_calibration_report.md`.

The isolated accuracy-first semantic evidence retriever and its provider,
hosting, caching, and integration guidance are documented in
[`docs/semantic_retrieval.md`](docs/semantic_retrieval.md).

## Mapping explanations

Every processed row includes a `Mapping Reason` column. The explanation states
the taxonomy basis for the selected canonical value and then adds supporting
provenance when applicable (reviewed override, approved historical mapping,
alias, similarity evidence, or model classification). Historical provenance is
never used as the explanation by itself. The same explanation appears in the
flagged-review interface and is updated when a reviewer confirms or changes a
selection. Reasons are deterministic and reused for duplicate decisions; they
do not require an additional API call per row.

## In-app user guidance

The Streamlit application includes one consolidated `Help & Field Guide` page:

- `Quick Start` explains the four-step operating workflow, file formats, output
  columns, and advanced settings.
- `Field Guide` lets a user choose a field once and then view result meanings,
  decision rules, country-specific rules, and approved examples together.
- `Common Questions` provides short answers for the most likely points of
  confusion.

The detailed AI prompts are read-only and are not exposed for editing in the
UI. `Review Corrections` remains a separate action page.

The app uses an explicit three-item navigation (`Standardize a File`, `Help &
Field Guide`, and `Review Corrections`) and a shared Trulioo-inspired theme from
`src/ui_theme.py`. The supplied light-green Trulioo wordmark is stored in
`assets/` and displayed consistently in the sidebar.

## Developer handoff export

Every downloaded workbook includes a `Developer Script` worksheet containing
unique finalized mappings, country-enum validation, template status, and a
generated constructor line when the field format is configured. The UI also
offers a separate `.cs` download when at least one line is ready.

The user-provided format configures the `~value~` delimiters and supplies
`BusinessTypeStandardization` as the initial example. Every supported field now
has a clearly labeled provisional constructor name so complete scripts can be
demonstrated before the developer contract is finalized. These names can be
changed in one configuration map later. The formatting example is never used as
mapping evidence.

The category names are read from `src/fields.py`, and automated tests require
every configured category to have matching guidance. The older external Word
definitions document is intentionally not embedded because it contains rules
that no longer match the reviewed classifier behavior.

## Layout

```
prompts/   field classification instructions, one file per field (added later)
data/      lookup, reviewed overrides, and git-ignored sample data
src/       application code
output/    generated / downloadable results (git-ignored contents)
.env       local secrets — API key (git-ignored, never committed)
```

## Setup

Python 3.11+ required (built and tested on 3.12).

```powershell
# 1. Create the virtual environment (already done if .venv exists)
python -m venv .venv

# 2. Install dependencies
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Configure the API key
copy .env.example .env
#    then edit .env and set ANTHROPIC_API_KEY to a real key
```

## API key

The key is loaded from a git-ignored `.env` file via `python-dotenv`
(`src/config.py`). It is never hardcoded. A real OS environment variable, if
set, takes precedence over `.env`.

> API access is still unconfirmed — check with your manager/IT whether Trulioo
> already has an Anthropic account before creating a personal key
> (Section 11 of the brief).

## Verify the environment

```powershell
# No API call — just checks imports, folders, and key loading:
.venv\Scripts\python.exe src\check_env.py

# Once a real key is in .env, confirm it works with one trivial live call:
.venv\Scripts\python.exe src\check_env.py --ping
```
