"""Common predictor contract and deterministic comparison helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from .models import EvaluationRecord, Prediction


class Predictor(Protocol):
    name: str

    def predict(self, record: EvaluationRecord) -> Prediction: ...


def run_predictor(
    records: Iterable[EvaluationRecord],
    predictor: Predictor,
) -> list[Prediction]:
    return [predictor.predict(record) for record in records]


@dataclass
class MockClassifier:
    """Deterministic test double; never imports or calls a live client."""

    name: str
    classifier: Callable[[EvaluationRecord], str]
    confidence: str = "HIGH"
    route: str = "api"
    api_bound: bool = True
    review: bool = False

    def predict(self, record: EvaluationRecord) -> Prediction:
        return Prediction(
            record_id=record.record_id,
            predicted_value=self.classifier(record),
            confidence=self.confidence,
            needs_review=self.review,
            route=self.route,
            api_bound=self.api_bound,
        )
