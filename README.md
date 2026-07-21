# Standardization Tool

A tool for KYC/AML field-content standardization: takes a file of raw entity/
relationship values in, returns standardized (canonical) values out, using the
classification logic already refined in Claude Projects. Built solo with Claude
Code. See the Master Project Brief for full context.

Currently at: **Phase 0 + Step 1 — project skeleton** (per Section 7 of the brief).

## Layout

```
prompts/   field classification instructions, one file per field (added later)
data/      sample raw-value files for testing (git-ignored contents)
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
