r"""Step 3 — Handle real file structure. Step 4 — batching, retry, logging.
Step 5 — multi-field support.

Takes a real-shaped input file and returns the SAME file with one column added,
without disturbing anything else:

  3.1  detect the raw-value column flexibly (--column, else auto-detect by a
       list of common header names).
  3.2  every other column passes through untouched.
  3.3  a "Standardized Value" column is inserted right next to the raw column.
  3.4  edge cases:
         - blank / whitespace-only raw values are filled locally (no API call),
         - duplicate raw values are classified ONCE and reused,
         - the unique values are chunked into batches so a big file never
           becomes one oversized API call.
  4.1  batch size is controllable (--batch-size) so batches fit the model's
       context window.
  4.2  each batch's API call goes through retry-with-backoff (src/retry.py)
       for transient errors (rate limits, timeouts, 5xx); a batch that
       exhausts its retries is marked distinctly rather than crashing the run.
  4.3  a run log entry (input/output counts, retries, mismatches, failures)
       is appended to output/run_log.jsonl and summarized on screen.
  5.1  each field's instructions live in their own file under /prompts.
  5.2  --field looks the field up in the registry (src/fields.py): field name
       -> prompt file -> expected standard values. Adding a field means adding
       one entry there — no changes needed here.
  5.3  the prompt loaded, and the catch-all value used for blanks, both come
       from whichever --field was selected instead of being hardcoded.
  8.1  the output contract now includes a confidence level (HIGH/MEDIUM/LOW)
       per value (src/classifier.py CONFIDENCE_ADDENDUM), appended to the
       field's prompt at load time.
  8.2  LOW-confidence, missing-confidence, and permanently-failed rows are
       surfaced in a "Needs Review" column instead of a separate review UI.

Still uses the simulated client by default (no API key). --live swaps in the
real Anthropic call; the file-handling logic here is identical either way.
--simulate-flaky / --simulate-broken inject REAL anthropic error types (no
live API needed) to prove the retry/logging actually work before real money
is spent.

Run:
    .venv\Scripts\python.exe src\standardize_file.py                                 # mock, Positions, sample file
    .venv\Scripts\python.exe src\standardize_file.py --field business_legal_form --data data\sample_blf.xlsx
    .venv\Scripts\python.exe src\standardize_file.py --data data\yourfile.xlsx
    .venv\Scripts\python.exe src\standardize_file.py --batch-size 5        # show chunking
    .venv\Scripts\python.exe src\standardize_file.py --simulate-flaky 2    # show retry recovery
    .venv\Scripts\python.exe src\standardize_file.py --simulate-broken     # show a batch giving up
    .venv\Scripts\python.exe src\standardize_file.py --live                # real API
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

import pandas as pd

import config
import fields
import run_log
from classifier import CONFIDENCE_ADDENDUM, MockClaudeClient, RealClaudeClient, classify_values
from fault_injection import FlakyClient, rate_limit_error, server_error
from jira_ticket import build_ticket_text, find_countries
from retry import RetryExhaustedError, call_with_retry

STANDARDIZED_COLUMN = "Standardized Value"
# Column header AND the flag value written into it when a row is flagged
# (blank otherwise) — a single constant serves both, by design.
NEEDS_REVIEW_COLUMN = "Needs Review"
DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_RETRY_BASE_DELAY = 1.0
DEFAULT_FIELD = "positions_designations"
# A batch that exhausts its retries gets this instead of silently vanishing.
# (Not a taxonomy value — always this literal, regardless of field.)
ERROR_FILL = "ERROR - Not Classified (API Failure)"

DEFAULT_DATA_FILE = config.DATA_DIR / "sample_positions_full.xlsx"

# Header names we'll accept as "the raw-value column" (compared case- and
# whitespace-insensitively). Section 9 notes the header varies: "Inputs",
# "Value", sometimes with a trailing space.
_VALUE_COLUMN_CANDIDATES = [
    "value", "raw value", "raw_value", "raw", "input", "inputs",
    "raw input", "original value", "original", "raw values",
]
_COUNTRY_COLUMN_CANDIDATES = ["country", "countries"]


@dataclass
class Stats:
    raw_column: str
    total_rows: int
    blanks: int
    unique_values: int
    duplicates_collapsed: int
    batches: int
    batch_size: int
    api_calls_saved: int  # rows that did NOT need an API call (dupes + blanks)
    flagged_count: int = 0  # rows marked Needs Review (LOW/missing confidence, blanks, failures)
    retries_used: int = 0
    failed_batches: list[run_log.BatchFailure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.warnings and not self.failed_batches


def _norm_key(value) -> str:
    """Normalize a raw cell to a dedup/lookup key ("" means blank)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return " ".join(str(value).split())


def detect_value_column(df: pd.DataFrame, user_specified: str | None = None) -> str:
    """Return the raw-value column: user's choice if given, else auto-detect."""
    if user_specified:
        if user_specified in df.columns:
            return user_specified
        raise ValueError(
            f"Column {user_specified!r} not found. Available: {list(df.columns)}"
        )

    normalized = {}
    for col in df.columns:
        normalized.setdefault(str(col).strip().lower(), col)

    matches = []
    for cand in _VALUE_COLUMN_CANDIDATES:
        if cand in normalized and normalized[cand] not in matches:
            matches.append(normalized[cand])

    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(
            "Could not auto-detect the raw-value column. Pass one with "
            f"--column. Available columns: {list(df.columns)}"
        )
    raise ValueError(
        f"Ambiguous raw-value column — candidates {matches}. "
        "Pick one with --column."
    )


def detect_country_column(df: pd.DataFrame) -> str | None:
    """Return the country column if one exists, else None (not an error —
    country context is optional; only used when the field is country_dependent)."""
    normalized = {str(col).strip().lower(): col for col in df.columns}
    for cand in _COUNTRY_COLUMN_CANDIDATES:
        if cand in normalized:
            return normalized[cand]
    return None


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _needs_review(confidence: str) -> bool:
    """LOW or missing/unparseable confidence needs a human look (8.2)."""
    return confidence in ("", "LOW")


def read_table(path: Path) -> pd.DataFrame:
    """Read an Excel or CSV file into a DataFrame."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(path)
    if suffix in (".csv", ".txt"):
        return pd.read_csv(path)
    raise ValueError(f"Unsupported file type: {suffix} (use .xlsx or .csv)")


def standardize_dataframe(
    df: pd.DataFrame,
    column: str,
    system_prompt: str,
    client,
    batch_size: int = DEFAULT_BATCH_SIZE,
    blank_fill: str = fields.CATCH_ALL,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    country_dependent: bool = False,
    country_column: str | None = None,
) -> tuple[pd.DataFrame, Stats]:
    """Add a standardized-value column next to `column`, everything else intact.

    country_dependent + country_column: when both are set, classification is
    keyed by (country, raw value) instead of raw value alone, and the model is
    told each value's country — needed for fields whose prompt has genuine
    per-country rules (Section 11 finding: ~3% of Positions/Designations
    values, e.g. "President", have a different correct answer per country).
    For every other field this is off, so dedup stays value-only (cheaper,
    and correct for them) — see fields.FieldSpec.country_dependent.
    """
    use_country = country_dependent and country_column is not None
    if use_country:
        country_values = [_norm_key(v) for v in df[country_column]]
    else:
        country_values = [""] * len(df)

    # Every row's key is a (country, raw_value) pair; country is "" when
    # country-awareness isn't in play, which collapses to the old value-only
    # behavior exactly (uniqueness is then driven by raw_value alone).
    keys: list[tuple[str, str]] = [
        (country_values[i], _norm_key(v)) for i, v in enumerate(df[column])
    ]
    blanks = sum(1 for _, raw in keys if raw == "")

    # 3.4 duplicates: classify each unique non-blank (country, value) pair once.
    unique_nonblank = list(dict.fromkeys(k for k in keys if k[1] != ""))

    # 4.1 chunking: never send the whole file as one call.
    # (country, value) -> (standardized_value, confidence); "" confidence flags for review.
    mapping: dict[tuple[str, str], tuple[str, str]] = {}
    warnings: list[str] = []
    failed_batches: list[run_log.BatchFailure] = []
    n_batches = 0
    retries_used = 0

    def _on_retry(attempt: int, exc: Exception, delay: float) -> None:
        nonlocal retries_used
        retries_used += 1
        print(
            f"    [retry] batch {n_batches}: attempt {attempt} failed "
            f"({type(exc).__name__}: {exc}) — waiting {delay:.1f}s before retry"
        )

    for chunk in _chunks(unique_nonblank, batch_size):
        n_batches += 1
        # What the model actually sees: country-prefixed when applicable,
        # otherwise identical to the old plain-value framing.
        display_values = [
            f"[Country: {country}] {raw}" if country else raw for country, raw in chunk
        ]
        try:
            # 4.2 retry/backoff wraps the whole classify call (build message +
            # API call + parse) — the API call inside is what can actually fail.
            batch = call_with_retry(
                classify_values,
                display_values,
                system_prompt,
                client,
                max_attempts=max_attempts,
                base_delay=retry_base_delay,
                on_retry=_on_retry,
            )
        except RetryExhaustedError as exc:
            print(f"    [FAILED] batch {n_batches} gave up after retries: {exc}")
            failed_batches.append(
                run_log.BatchFailure(batch_index=n_batches, values=list(display_values), error=str(exc))
            )
            for k in chunk:
                # "" confidence -> always flagged, regardless of ERROR_FILL's text.
                mapping[k] = (ERROR_FILL, "")
            continue

        warnings.extend(f"batch {n_batches}: {w}" for w in batch.warnings)
        # Align by position (guaranteed by parse_response), not by matching
        # r.raw_value text — the model sees the country-prefixed string, but
        # the mapping key must be the original (country, raw) tuple.
        for k, r in zip(chunk, batch.results):
            mapping[k] = (r.standardized_value, r.confidence)

    # Build both new columns, aligned row-for-row with the original. Blanks
    # are auto-filled with no real classification attempt, so they're always
    # flagged too (8.2) — not a real answer, just a placeholder.
    standardized: list[str] = []
    needs_review: list[str] = []
    for k in keys:
        if k[1] == "":
            standardized.append(blank_fill)
            needs_review.append(NEEDS_REVIEW_COLUMN)
            continue
        value, confidence = mapping.get(k, ("", ""))
        standardized.append(value)
        needs_review.append(NEEDS_REVIEW_COLUMN if _needs_review(confidence) else "")

    # 3.2 passthrough + 3.3 insert next to the raw column.
    result = df.copy()
    result = result.drop(columns=[c for c in (STANDARDIZED_COLUMN, NEEDS_REVIEW_COLUMN) if c in result.columns])
    insert_at = result.columns.get_loc(column) + 1
    result.insert(insert_at, STANDARDIZED_COLUMN, standardized)
    result.insert(insert_at + 1, NEEDS_REVIEW_COLUMN, needs_review)

    non_blank_rows = len(keys) - blanks
    stats = Stats(
        raw_column=column,
        total_rows=len(df),
        blanks=blanks,
        unique_values=len(unique_nonblank),
        duplicates_collapsed=non_blank_rows - len(unique_nonblank),
        batches=n_batches,
        batch_size=batch_size,
        api_calls_saved=(non_blank_rows - len(unique_nonblank)) + blanks,
        flagged_count=needs_review.count(NEEDS_REVIEW_COLUMN),
        retries_used=retries_used,
        failed_batches=failed_batches,
        warnings=warnings,
    )
    return result, stats


def standardize_file(
    path: Path,
    system_prompt: str,
    client,
    column: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    output_dir: Path = config.OUTPUT_DIR,
    country_dependent: bool = False,
) -> tuple[pd.DataFrame, Stats, Path]:
    df = read_table(path)
    raw_col = detect_value_column(df, column)
    country_col = detect_country_column(df) if country_dependent else None
    result, stats = standardize_dataframe(
        df, raw_col, system_prompt, client, batch_size,
        country_dependent=country_dependent, country_column=country_col,
    )
    out_path = output_dir / f"{path.stem}_standardized.xlsx"
    result.to_excel(out_path, index=False)
    return result, stats, out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 3/4/5 — standardize a real file")
    parser.add_argument(
        "--field", default=DEFAULT_FIELD, choices=sorted(fields.FIELDS),
        help="which taxonomy field to apply (looked up in the registry, src/fields.py)",
    )
    parser.add_argument("--data", type=Path, default=None,
                         help=f"defaults to {DEFAULT_DATA_FILE} if omitted")
    parser.add_argument("--prompt", type=Path, default=None,
                         help="override: use this prompt file instead of the field's registered one")
    parser.add_argument("--column", default=None, help="raw-value column (else auto-detect)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS,
                         help="max attempts per batch before giving up")
    parser.add_argument("--retry-base-delay", type=float, default=DEFAULT_RETRY_BASE_DELAY,
                         help="seconds to wait before the first retry (doubles each attempt)")
    parser.add_argument("--live", action="store_true", help="use the real Anthropic API")
    parser.add_argument(
        "--simulate-flaky", type=int, default=0, metavar="N",
        help="inject N simulated transient errors (real anthropic.RateLimitError) "
             "then succeed — demonstrates retry recovering within budget",
    )
    parser.add_argument(
        "--simulate-broken", action="store_true",
        help="inject enough simulated errors to exhaust the first batch's retries "
             "(real anthropic.InternalServerError) — demonstrates a permanently "
             "failed batch being logged distinctly while the rest of the run completes",
    )
    parser.add_argument(
        "--no-ticket", action="store_true",
        help="skip generating the ready-to-paste Jira ticket content after the run",
    )
    args = parser.parse_args()

    spec = fields.get(args.field)
    data_path = args.data or DEFAULT_DATA_FILE
    blank_fill = spec.standard_values[-1]  # this field's own catch-all value

    if not data_path.exists():
        print(f"Data file not found: {data_path}")
        print("Generate samples first: .venv\\Scripts\\python.exe src\\_make_sample_data.py")
        return 1

    df = read_table(data_path)
    original_columns = list(df.columns)

    try:
        raw_col = detect_value_column(df, args.column)
    except ValueError as exc:
        print(f"[!] {exc}")
        return 1

    if args.prompt:
        prompt_path = args.prompt
        # Match spec.load_prompt()'s behavior: append the Step 8 confidence
        # contract even for an overridden prompt file, since parse_response
        # now expects every response in that format.
        system_prompt = prompt_path.read_text(encoding="utf-8").rstrip() + "\n\n" + CONFIDENCE_ADDENDUM
    else:
        prompt_path = spec.prompt_path
        system_prompt = spec.load_prompt()
    client = RealClaudeClient() if args.live else MockClaudeClient(field_key=args.field)

    if args.simulate_broken:
        # Exactly enough failures to exhaust the FIRST batch's retry budget,
        # then let every later batch through — shows the run survives one
        # bad batch instead of crashing entirely.
        client = FlakyClient(client, fail_times=args.max_attempts, error_factory=server_error)
    elif args.simulate_flaky:
        client = FlakyClient(client, fail_times=args.simulate_flaky, error_factory=rate_limit_error)

    print(f"Field            : {spec.display_name}  (key: {spec.key})")
    if spec.notes:
        print(f"  NOTE: {spec.notes}")
    print(f"Loaded {len(df)} rows from {data_path.name}")
    print(f"  columns          : {original_columns}")
    print(f"  raw-value column : {raw_col!r}  "
          f"({'you specified' if args.column else 'auto-detected'})")
    print(f"  prompt file      : {prompt_path.name}")
    print(f"  client           : {client.name}")
    print(f"  batch size       : {args.batch_size}")
    print(f"  retry policy     : max {args.max_attempts} attempts, "
          f"{args.retry_base_delay}s base backoff")
    if not args.live:
        print("  NOTE: values are SIMULATED (mock). --live uses the real API; "
              "the file handling is identical.")
        if args.field not in ("positions_designations", "business_legal_form"):
            print(f"  NOTE: mock has no keyword heuristic for {args.field!r} — every "
                  f"value will fall back to {blank_fill!r}. This proves the pipeline "
                  "(field lookup, batching, retry, logging) works for this field; "
                  "real classification needs --live.")

    country_col = detect_country_column(df) if spec.country_dependent else None
    if spec.country_dependent:
        if country_col:
            print(f"  country column   : {country_col!r}  "
                  "(classifying per (country, value) pair — see field notes)")
        else:
            print("  NOTE: this field is country-dependent but no country column was "
                  "found — falling back to value-only classification (same as before).")

    result, stats = standardize_dataframe(
        df, raw_col, system_prompt, client,
        batch_size=args.batch_size,
        blank_fill=blank_fill,
        max_attempts=args.max_attempts,
        retry_base_delay=args.retry_base_delay,
        country_dependent=spec.country_dependent,
        country_column=country_col,
    )

    # Show a preview with the raw column and the new columns side by side.
    preview_cols = [raw_col, STANDARDIZED_COLUMN, NEEDS_REVIEW_COLUMN]
    if "country" in result.columns:
        preview_cols = ["country"] + preview_cols
    print("\nPreview (first 12 rows):")
    with pd.option_context("display.max_rows", 12, "display.width", 120):
        print(result[preview_cols].head(12).to_string(index=False))

    # 3.2 verify passthrough — no original column lost or altered in place.
    passthrough_ok = all(c in result.columns for c in original_columns)
    inserted_right = list(result.columns).index(STANDARDIZED_COLUMN) == \
        list(result.columns).index(raw_col) + 1

    out_path = config.OUTPUT_DIR / f"{data_path.stem}_standardized.xlsx"
    result.to_excel(out_path, index=False)

    print("\n" + "-" * 68)
    print(f"  total rows            : {stats.total_rows}")
    print(f"  blank/empty raw       : {stats.blanks}  (filled as {blank_fill!r}, no API call)")
    print(f"  unique values sent    : {stats.unique_values}")
    print(f"  duplicates reused     : {stats.duplicates_collapsed}")
    print(f"  API batches           : {stats.batches}  (size {stats.batch_size})")
    print(f"  rows needing no call  : {stats.api_calls_saved}  (dupes + blanks)")
    print(f"  flagged for review    : {stats.flagged_count}  "
          f"(LOW/missing confidence, blanks, or API failures)")
    print(f"  all columns preserved : {'YES' if passthrough_ok else 'NO'}")
    print(f"  new column placed     : {'next to raw column' if inserted_right else 'MISPLACED'}")

    # 4.3 run log — write the JSONL record and print its summary.
    record = run_log.new_record(
        source_file=str(data_path),
        raw_column=raw_col,
        total_rows=stats.total_rows,
        blank_rows=stats.blanks,
        unique_values_sent=stats.unique_values,
        duplicates_reused=stats.duplicates_collapsed,
        batches_total=stats.batches,
        batches_failed=len(stats.failed_batches),
        retries_used=stats.retries_used,
        flagged_count=stats.flagged_count,
        mismatches=stats.warnings,
        failures=stats.failed_batches,
    )
    run_log.write(record)
    print(f"  retries used          : {stats.retries_used}")
    print(f"  batches failed        : {len(stats.failed_batches)}")
    if stats.failed_batches:
        for f in stats.failed_batches:
            preview = ", ".join(f.values[:3]) + ("…" if len(f.values) > 3 else "")
            print(f"      - batch {f.batch_index} [{preview}] -> marked {ERROR_FILL!r}")
    print(f"  run logged to         : {run_log.LOG_FILE}")

    all_ok = stats.ok and passthrough_ok and inserted_right
    print(f"  status                : {'PASS' if all_ok else 'WARNINGS'}")
    if not all_ok:
        for w in stats.warnings:
            print(f"      - {w}")
    print(f"  saved                 : {out_path}")
    print("-" * 68)

    # Section 5 item 8 — ready-to-paste Jira ticket content for the
    # engineering handoff (NOT a live Jira API call — see Section 6).
    if not args.no_ticket:
        countries = find_countries(df)
        ticket_text = build_ticket_text(spec.display_name, raw_col, countries, out_path.name)
        ticket_path = config.OUTPUT_DIR / f"{data_path.stem}_jira_ticket.txt"
        ticket_path.write_text(ticket_text, encoding="utf-8")
        print("\nJira ticket content (ready to paste):")
        print("=" * 68)
        print(ticket_text)
        print("=" * 68)
        print(f"Saved to: {ticket_path}")

    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
