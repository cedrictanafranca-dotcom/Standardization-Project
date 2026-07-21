r"""Step 4.3 — basic run logging.

One JSON-lines entry per run, appended to output/run_log.jsonl, plus a console
summary. Enough to answer "did this run behave?" at a glance: how many rows
went in, how many came out, how many needed a retry, and whether any batch
permanently failed — without a dashboard or a separate log viewer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import config

LOG_FILE = config.OUTPUT_DIR / "run_log.jsonl"


@dataclass
class BatchFailure:
    batch_index: int
    values: list[str]
    error: str


@dataclass
class RunRecord:
    timestamp: str
    source_file: str
    raw_column: str
    total_rows: int
    blank_rows: int
    unique_values_sent: int
    duplicates_reused: int
    batches_total: int
    batches_failed: int
    retries_used: int
    flagged_count: int = 0  # rows marked Needs Review (Step 8.2)
    mismatches: list[str] = field(default_factory=list)
    failures: list[BatchFailure] = field(default_factory=list)

    @property
    def output_count(self) -> int:
        """Rows that ended up with a non-empty standardized value."""
        return self.total_rows - sum(len(f.values) for f in self.failures)

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False)


def write(record: RunRecord, log_file: Path = LOG_FILE) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(record.to_json() + "\n")


def new_record(
    source_file: str,
    raw_column: str,
    total_rows: int,
    blank_rows: int,
    unique_values_sent: int,
    duplicates_reused: int,
    batches_total: int,
    batches_failed: int,
    retries_used: int,
    mismatches: list[str],
    failures: list[BatchFailure],
    flagged_count: int = 0,
) -> RunRecord:
    return RunRecord(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_file=source_file,
        raw_column=raw_column,
        total_rows=total_rows,
        blank_rows=blank_rows,
        unique_values_sent=unique_values_sent,
        duplicates_reused=duplicates_reused,
        batches_total=batches_total,
        batches_failed=batches_failed,
        retries_used=retries_used,
        flagged_count=flagged_count,
        mismatches=mismatches,
        failures=failures,
    )


def print_summary(record: RunRecord) -> None:
    print(f"  input rows       : {record.total_rows}")
    print(f"  output rows      : {record.output_count}  "
          f"(rows classified or blank-filled)")
    print(f"  flagged review   : {record.flagged_count}")
    print(f"  retries used     : {record.retries_used}")
    print(f"  batches          : {record.batches_total}  "
          f"({record.batches_failed} permanently failed)")
    if record.mismatches:
        print(f"  mismatches       : {len(record.mismatches)}")
        for m in record.mismatches:
            print(f"      - {m}")
    if record.failures:
        print(f"  FAILED batches   :")
        for f in record.failures:
            preview = ", ".join(f.values[:3]) + ("…" if len(f.values) > 3 else "")
            print(f"      - batch {f.batch_index}: [{preview}] -> {f.error}")
