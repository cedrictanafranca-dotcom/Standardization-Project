r"""Build the master lookup table from the master remapping Excel file.

Reads all 10 field sheets, applies conflict resolutions (from master_lookup.RESOLUTIONS),
and writes data/master_lookup.json — the pre-flight cache used by the pipeline
to resolve known raw values without calling the Claude API.

Run once, then re-run whenever the master file changes:
    .venv\Scripts\python.exe src\build_lookup.py
    .venv\Scripts\python.exe src\build_lookup.py --master-file "C:\path\to\file.xlsx"
    .venv\Scripts\python.exe src\build_lookup.py --fields positions_designations brn_type
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import master_lookup as ml


def main() -> int:
    parser = argparse.ArgumentParser(description="Build master_lookup.json from the master Excel file")
    parser.add_argument(
        "--master-file", type=Path, default=ml.DEFAULT_MASTER_FILE,
        help=f"path to master remapping xlsx (default: {ml.DEFAULT_MASTER_FILE})",
    )
    parser.add_argument(
        "--output-file", type=Path, default=ml.DEFAULT_LOOKUP_FILE,
        help=f"where to write the JSON lookup (default: {ml.DEFAULT_LOOKUP_FILE})",
    )
    parser.add_argument(
        "--fields", nargs="+", default=None,
        choices=sorted(ml.SHEET_BY_FIELD),
        metavar="FIELD",
        help="subset of fields to build (default: all 10)",
    )
    args = parser.parse_args()

    try:
        lookups = ml.build_from_master_file(
            master_file=args.master_file,
            output_file=args.output_file,
            field_keys=args.fields,
            verbose=True,
        )
    except FileNotFoundError as exc:
        print(f"[!] {exc}")
        print("    Check the path or pass --master-file.")
        return 1

    print(f"\nDone. {len(lookups)} field(s) built.")
    print("The pipeline will use this lookup automatically on next run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
