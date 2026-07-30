"""Measured automation policy for high-coverage deterministic decisions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class SimilarityEvidence:
    """Signals used to decide whether a neighbor prediction is automatable."""

    predicted_value: str = ""
    score: float = 0.0
    margin: float = 0.0
    agreement: float = 0.0
    support: int = 0
    conflicting_labels: tuple[str, ...] = ()

    @property
    def has_prediction(self) -> bool:
        return bool(self.predicted_value)


@dataclass(frozen=True)
class SimilarityRule:
    """One field's validation-backed automatic-acceptance threshold."""

    enabled: bool
    min_score: float
    min_margin: float
    min_agreement: float
    min_support: int
    calibration_precision: float
    calibration_coverage: float
    calibration_count: int
    validation_precision: float
    validation_coverage: float
    validation_count: int
    reason: str = ""

    def accepts(self, evidence: SimilarityEvidence) -> bool:
        return (
            self.enabled
            and evidence.has_prediction
            and evidence.score >= self.min_score
            and evidence.margin >= self.min_margin
            and evidence.agreement >= self.min_agreement
            and evidence.support >= self.min_support
        )


@dataclass(frozen=True)
class AliasRule:
    """Field-level decision on whether approved aliases may auto-resolve."""

    enabled: bool
    observed_precision: float
    observed_count: int
    reason: str = ""


@dataclass(frozen=True)
class AutomationPolicy:
    """Versioned, source-bound rules created by offline calibration."""

    schema_version: int
    target_precision: float
    source_lookup_sha256: str
    split_seed: int
    alias_rules: dict[str, AliasRule]
    similarity_rules: dict[str, SimilarityRule]

    def accepts_alias(self, field_key: str) -> bool:
        rule = self.alias_rules.get(field_key)
        return bool(rule and rule.enabled)

    def similarity_rule(self, field_key: str) -> SimilarityRule | None:
        return self.similarity_rules.get(field_key)

    def accepts_similarity(
        self,
        field_key: str,
        evidence: SimilarityEvidence,
    ) -> bool:
        rule = self.similarity_rule(field_key)
        return bool(rule and rule.accepts(evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target_precision": self.target_precision,
            "source_lookup_sha256": self.source_lookup_sha256,
            "split_seed": self.split_seed,
            "alias_rules": {
                field: asdict(rule)
                for field, rule in sorted(self.alias_rules.items())
            },
            "similarity_rules": {
                field: asdict(rule)
                for field, rule in sorted(self.similarity_rules.items())
            },
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AutomationPolicy":
        if int(value.get("schema_version", 0)) != 1:
            raise ValueError("automation policy schema_version must be 1")
        target = float(value.get("target_precision", 0.0))
        if not 0.0 < target <= 1.0:
            raise ValueError("target_precision must be in (0, 1]")
        rules = {
            str(field): SimilarityRule(**rule)
            for field, rule in dict(value.get("similarity_rules", {})).items()
        }
        alias_rules = {
            str(field): AliasRule(**rule)
            for field, rule in dict(value.get("alias_rules", {})).items()
        }
        return cls(
            schema_version=1,
            target_precision=target,
            source_lookup_sha256=str(value.get("source_lookup_sha256", "")),
            split_seed=int(value.get("split_seed", 0)),
            alias_rules=alias_rules,
            similarity_rules=rules,
        )


def load_automation_policy(path: str | Path) -> AutomationPolicy:
    return AutomationPolicy.from_dict(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def summarize_similarity_matches(
    matches: Sequence[object],
    *,
    near_top_window: float = 0.04,
) -> SimilarityEvidence:
    """Summarize FieldLookup-like matches without importing master_lookup."""
    if not matches:
        return SimilarityEvidence()
    ordered = sorted(
        matches,
        key=lambda item: (-float(getattr(item, "score")), str(getattr(item, "raw_value"))),
    )
    top = ordered[0]
    top_score = float(getattr(top, "score"))
    top_label = str(getattr(top, "standardized_value"))
    near = [
        item
        for item in ordered
        if float(getattr(item, "score")) >= top_score - near_top_window
    ]
    agreeing = sum(
        str(getattr(item, "standardized_value")) == top_label for item in near
    )
    other_scores = [
        float(getattr(item, "score"))
        for item in ordered
        if str(getattr(item, "standardized_value")) != top_label
    ]
    best_other = max(other_scores, default=0.0)
    conflicts = tuple(sorted({
        str(getattr(item, "standardized_value"))
        for item in near
        if str(getattr(item, "standardized_value")) != top_label
    }))
    return SimilarityEvidence(
        predicted_value=top_label,
        score=top_score,
        margin=top_score - best_other if best_other else top_score,
        agreement=agreeing / len(near),
        support=len(near),
        conflicting_labels=conflicts,
    )
