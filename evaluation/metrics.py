"""Accuracy and operational metrics shared by every evaluated approach."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Iterable

from .dataset import CATCH_ALL
from .models import EvaluationRecord, Prediction


def _bucket(
    records: list[EvaluationRecord],
    predictions: dict[str, Prediction],
    key: Callable[[EvaluationRecord], str],
) -> dict[str, dict[str, float | int]]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in records:
        label = key(record)
        totals[label][1] += 1
        prediction = predictions[record.record_id]
        totals[label][0] += int(prediction.predicted_value == record.expected_value)
    return {
        label: {
            "correct": correct,
            "total": total,
            "accuracy": correct / total if total else 0.0,
        }
        for label, (correct, total) in sorted(totals.items())
    }


def score_predictions(
    records: Iterable[EvaluationRecord],
    predictions: Iterable[Prediction],
    approach: str,
) -> dict:
    records_list = list(records)
    prediction_list = list(predictions)
    by_id = {prediction.record_id: prediction for prediction in prediction_list}
    if len(by_id) != len(prediction_list):
        raise ValueError("prediction file contains duplicate record_id values")
    expected_ids = {record.record_id for record in records_list}
    missing = expected_ids - set(by_id)
    extra = set(by_id) - expected_ids
    if missing or extra:
        raise ValueError(
            f"prediction IDs do not match dataset: missing={len(missing)}, extra={len(extra)}"
        )

    correct = sum(
        by_id[record.record_id].predicted_value == record.expected_value
        for record in records_list
    )
    incorrect_high = sum(
        by_id[record.record_id].confidence.upper() == "HIGH"
        and by_id[record.record_id].predicted_value != record.expected_value
        for record in records_list
    )
    catch_all = sum(
        prediction.predicted_value == CATCH_ALL for prediction in prediction_list
    )
    review = sum(
        prediction.needs_review or prediction.confidence.upper() in ("", "LOW")
        for prediction in prediction_list
    )
    predictive = sum(
        prediction.route.lower() == "predictive" for prediction in prediction_list
    )
    api_bound = sum(prediction.api_bound for prediction in prediction_list)
    total = len(records_list)

    return {
        "approach": approach,
        "total": total,
        "correct": correct,
        "overall_accuracy": correct / total if total else 0.0,
        "incorrect_high": {
            "count": incorrect_high,
            "rate": incorrect_high / total if total else 0.0,
        },
        "catch_all_rate": catch_all / total if total else 0.0,
        "review_rate": review / total if total else 0.0,
        "predictive_coverage": predictive / total if total else 0.0,
        "api_bound_values": {
            "count": api_bound,
            "rate": api_bound / total if total else 0.0,
        },
        "accuracy_by_field": _bucket(
            records_list, by_id, lambda record: record.field
        ),
        "accuracy_by_category": _bucket(
            records_list,
            by_id,
            lambda record: f"{record.field}::{record.expected_value}",
        ),
        "accuracy_by_country": _bucket(
            records_list, by_id, lambda record: record.country or "[GLOBAL]"
        ),
        "accuracy_by_frequency": _bucket(
            records_list, by_id, lambda record: record.frequency_band
        ),
        "accuracy_by_ambiguity": _bucket(
            records_list,
            by_id,
            lambda record: "ambiguous" if record.ambiguous else "unambiguous",
        ),
    }
