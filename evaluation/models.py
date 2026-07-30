"""Small, dependency-free data contracts used by the evaluation package."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvaluationRecord:
    record_id: str
    field: str
    raw_value: str
    expected_value: str
    country: str = ""
    family_id: str = ""
    frequency_band: str = "rare"
    ambiguous: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvaluationRecord":
        return cls(**{name: value.get(name, default)
                      for name, default in (
                          ("record_id", ""),
                          ("field", ""),
                          ("raw_value", ""),
                          ("expected_value", ""),
                          ("country", ""),
                          ("family_id", ""),
                          ("frequency_band", "rare"),
                          ("ambiguous", False),
                      )})


@dataclass(frozen=True)
class Prediction:
    record_id: str
    predicted_value: str
    confidence: str = ""
    needs_review: bool = False
    route: str = "api"
    api_bound: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Prediction":
        confidence = str(value.get("confidence", ""))
        return cls(
            record_id=str(value["record_id"]),
            predicted_value=str(value.get("predicted_value", "")),
            confidence=confidence,
            needs_review=bool(
                value.get("needs_review", confidence in ("", "LOW"))
            ),
            route=str(value.get("route", "api")),
            api_bound=bool(value.get("api_bound", True)),
            metadata=dict(value.get("metadata", {})),
        )
