"""Optional live prompt-only or retrieval-assisted evaluation.

Nothing in this module runs at import time. A live call requires both --live
and the exact --cost-approval acknowledgement.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from .dataset import load_jsonl
from .families import similarity
from .models import EvaluationRecord, Prediction

COST_APPROVAL = "I_APPROVE_LIVE_API_COST"


def _load_reference(path: Path) -> list[EvaluationRecord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records: list[EvaluationRecord] = []
    for field, field_data in data.items():
        for raw, expected in field_data.get("consistent", {}).items():
            records.append(EvaluationRecord("", field, raw, expected))
        for country, country_map in field_data.get("by_country", {}).items():
            for raw, expected in country_map.items():
                records.append(EvaluationRecord("", field, raw, expected, country))
    return records


def _retrieval_examples(
    record: EvaluationRecord,
    candidates: list[EvaluationRecord],
    limit: int = 5,
) -> list[tuple[str, str, float]]:
    ranked = []
    for candidate in candidates:
        if candidate.field != record.field:
            continue
        if record.country and candidate.country not in ("", record.country):
            continue
        score = similarity(record.raw_value, candidate.raw_value)
        if score >= 0.45:
            prefix = f"[Country: {candidate.country}] " if candidate.country else ""
            ranked.append((score, prefix + candidate.raw_value, candidate.expected_value))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [(raw, expected, score) for score, raw, expected in ranked[:limit]]


def run_live(
    dataset_path: Path,
    reference_path: Path,
    output_path: Path,
    approach: str,
    batch_size: int,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "src"))
    from classifier import RealClaudeClient, classify_values
    import fields

    heldout = load_jsonl(dataset_path)
    reference = _load_reference(reference_path)
    client = RealClaudeClient()
    predictions: list[Prediction] = []
    by_field: dict[str, list[EvaluationRecord]] = defaultdict(list)
    for record in heldout:
        by_field[record.field].append(record)

    for field, records in sorted(by_field.items()):
        spec = fields.get(field)
        for start in range(0, len(records), batch_size):
            chunk = records[start:start + batch_size]
            display_values = [
                f"[Country: {record.country}] {record.raw_value}"
                if record.country else record.raw_value
                for record in chunk
            ]
            approved_examples = None
            if approach == "retrieval-assisted":
                approved_examples = [
                    _retrieval_examples(record, reference) for record in chunk
                ]
            batch = classify_values(
                display_values,
                spec.load_prompt(),
                client,
                approved_examples,
            )
            for record, result in zip(chunk, batch.results):
                predicted = result.standardized_value
                confidence = result.confidence
                if predicted not in spec.standard_values:
                    predicted = "Other / Unclassified"
                    confidence = "LOW"
                predictions.append(Prediction(
                    record_id=record.record_id,
                    predicted_value=predicted,
                    confidence=confidence,
                    needs_review=confidence in ("", "LOW"),
                    route=approach,
                    api_bound=True,
                    metadata={"warnings": batch.warnings},
                ))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(item.to_dict(), ensure_ascii=False) + "\n"
                for item in predictions),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--approach",
        choices=("prompt-only", "retrieval-assisted"),
        required=True,
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--cost-approval", default="")
    args = parser.parse_args()
    if not args.live or args.cost_approval != COST_APPROVAL:
        parser.error(
            "live calls are disabled; pass --live and "
            f"--cost-approval {COST_APPROVAL} only after explicit approval"
        )
    run_live(
        args.dataset,
        args.reference,
        args.output,
        args.approach,
        args.batch_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
