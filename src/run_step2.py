r"""Step 2 demo — classify one field, one file, end to end.

Reads one Excel file into a DataFrame (2.1), selects the raw-value column
(hardcoded for now — 2.2), sends the values through the classifier using a
structured, numbered output contract (2.3/2.4), and verifies that the raw-value
order lines up exactly with the standardized output order (2.5).

Runs against a SIMULATED Claude client by default — no API key, no network —
so you can see exactly what the pipeline produces before a real key exists.
Add --live to use the real Anthropic API instead (needs a key in .env).

Run:
    .venv\Scripts\python.exe src\run_step2.py
    .venv\Scripts\python.exe src\run_step2.py --live       # once a key exists
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Multilingual titles (Konateľ, Geschäftsführer) break the default Windows
# console codepage; force UTF-8 output so they print cleanly.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover - older interpreters
    pass

import pandas as pd

import config
import fields
from classifier import (
    CONFIDENCE_ADDENDUM,
    MockClaudeClient,
    RealClaudeClient,
    classify_values,
)

# Step 2 hardcodes these; Step 3 makes column detection flexible, Step 5 adds
# the field registry — the prompt path is now sourced from there instead of
# being duplicated as a second hardcoded path.
DEFAULT_DATA_FILE = config.DATA_DIR / "sample_positions.xlsx"
DEFAULT_PROMPT_FILE = fields.get("positions_designations").prompt_path
RAW_VALUE_COLUMN = "value"


def load_prompt(path: Path) -> str:
    """Field instructions plus the Step 8 confidence contract — matches
    fields.py's FieldSpec.load_prompt() so --live gets the same contract."""
    return path.read_text(encoding="utf-8").rstrip() + "\n\n" + CONFIDENCE_ADDENDUM


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 2 single-field classification demo")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_FILE)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT_FILE)
    parser.add_argument("--column", default=RAW_VALUE_COLUMN, help="raw-value column name")
    parser.add_argument("--live", action="store_true", help="use the real Anthropic API")
    args = parser.parse_args()

    # --- 2.1 read one Excel file into a DataFrame ---------------------------
    if not args.data.exists():
        print(f"Data file not found: {args.data}")
        print("Generate the sample first: .venv\\Scripts\\python.exe src\\_make_sample_data.py")
        return 1
    df = pd.read_excel(args.data)
    print(f"Loaded {len(df)} rows from {args.data.name}  (columns: {list(df.columns)})")

    # --- 2.2 select the raw-value column -----------------------------------
    if args.column not in df.columns:
        print(f"Column {args.column!r} not in file. Available: {list(df.columns)}")
        return 1
    raw_values = [("" if pd.isna(v) else str(v)) for v in df[args.column].tolist()]

    # --- pick the client (mock vs real) ------------------------------------
    system_prompt = load_prompt(args.prompt)
    client = RealClaudeClient() if args.live else MockClaudeClient()

    print()
    print("=" * 68)
    print(f"  Client : {client.name}")
    print(f"  Model  : {config.get_model() if args.live else '(simulated locally)'}")
    print(f"  Prompt : {args.prompt.name}  ({len(system_prompt):,} chars)")
    print(f"  Batch  : {len(raw_values)} raw values from column {args.column!r}")
    print("=" * 68)
    if not args.live:
        print("  NOTE: responses below are SIMULATED. Re-run with --live and a")
        print("        real key in .env to hit the actual Claude API — the code")
        print("        path is identical; only the client changes.")
        print("=" * 68)

    # --- 2.3/2.4 classify via structured output contract -------------------
    batch = classify_values(raw_values, system_prompt, client)

    # --- 2.5 show alignment: raw value next to standardized value ----------
    width = max((len(v) for v in raw_values), default=10)
    width = min(max(width, 12), 40)
    print()
    print(f"  {'#':>3}  {'RAW VALUE':<{width}}  ->  STANDARDIZED VALUE{'':<20}CONF  REVIEW?")
    print(f"  {'-'*3}  {'-'*width}  --  {'-'*25}  ----  -------")
    for r in batch.results:
        shown = (r.raw_value if r.raw_value != "" else "(blank)")
        if len(shown) > width:
            shown = shown[: width - 1] + "…"
        flag = "NEEDS REVIEW" if r.needs_review else ""
        print(f"  {r.index:>3}  {shown:<{width}}  ->  {r.standardized_value:<25}  {r.confidence:<4}  {flag}")

    # --- summary + alignment verdict ---------------------------------------
    print()
    print("-" * 68)
    print(f"  inputs sent      : {batch.total_expected}")
    print(f"  outputs returned : {sum(1 for r in batch.results if r.standardized_value)}")
    print(f"  model total line : {batch.total_reported}")
    if batch.ok:
        print("  alignment check  : PASS — every input has an output, in order.")
    else:
        print("  alignment check  : WARNINGS —")
        for w in batch.warnings:
            print(f"      - {w}")
    print("-" * 68)

    return 0 if batch.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
