"""Offline calibration of deterministic automation routes.

This module never constructs a live classifier or embedding client. Thresholds
are selected on one family-disjoint partition and reported on another.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from automation_policy import (  # noqa: E402
    AliasRule,
    AutomationPolicy,
    SimilarityEvidence,
    SimilarityRule,
    summarize_similarity_matches,
)
from lexical_aliases import LexicalAliasMatcher, MatchOutcome, load_default_matcher  # noqa: E402
from master_lookup import FieldLookup  # noqa: E402

from .families import normalize_value
from .models import EvaluationRecord


@dataclass(frozen=True)
class RouteObservation:
    record: EvaluationRecord
    route: str
    predicted_value: str = ""
    evidence: SimilarityEvidence = SimilarityEvidence()

    @property
    def correct(self) -> bool:
        return bool(self.predicted_value) and (
            self.predicted_value == self.record.expected_value
        )


def load_reference_lookups(path: Path) -> dict[str, FieldLookup]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        field: FieldLookup(
            field_key=field,
            consistent=dict(value.get("consistent", {})),
            by_country={
                country: dict(mappings)
                for country, mappings in value.get("by_country", {}).items()
            },
        )
        for field, value in payload.items()
    }


def observe_routes(
    records: Iterable[EvaluationRecord],
    lookups: dict[str, FieldLookup],
    alias_matcher: LexicalAliasMatcher | None = None,
) -> list[RouteObservation]:
    matcher = alias_matcher or load_default_matcher()
    observations: list[RouteObservation] = []
    for record in records:
        lookup = lookups.get(record.field)
        if lookup is None:
            observations.append(RouteObservation(record, "unresolved"))
            continue
        exact = lookup.get(record.raw_value, record.country)
        if exact is not None:
            observations.append(RouteObservation(record, "exact", exact))
            continue
        alias = matcher.match(record.field, record.raw_value, record.country)
        if alias.outcome is MatchOutcome.MATCH:
            observations.append(RouteObservation(
                record,
                "alias",
                alias.canonical_value or "",
            ))
            continue
        if alias.outcome is MatchOutcome.REVIEW:
            observations.append(RouteObservation(
                record,
                "modifier_review",
                alias.suggested_value or "",
            ))
            continue
        matches = lookup.similar(
            record.raw_value,
            record.country,
            limit=8,
            min_score=0.0,
        )
        evidence = summarize_similarity_matches(matches)
        observations.append(RouteObservation(
            record,
            "similarity" if evidence.has_prediction else "unresolved",
            evidence.predicted_value,
            evidence,
        ))
    return observations


def split_observations(
    observations: Iterable[RouteObservation],
    *,
    seed: int,
    calibration_fraction: float = 0.60,
) -> tuple[list[RouteObservation], list[RouteObservation]]:
    if not 0.0 < calibration_fraction < 1.0:
        raise ValueError("calibration_fraction must be in (0, 1)")
    observation_list = list(observations)
    by_family: dict[str, list[RouteObservation]] = defaultdict(list)
    for observation in observation_list:
        family = observation.record.family_id or observation.record.record_id
        by_family[family].append(observation)

    by_stratum: dict[tuple[str, str], list[tuple[str, list[RouteObservation]]]] = defaultdict(list)
    for family, members in by_family.items():
        route = Counter(item.route for item in members).most_common(1)[0][0]
        by_stratum[(members[0].record.field, route)].append((family, members))

    calibration: list[RouteObservation] = []
    validation: list[RouteObservation] = []
    family_side: dict[str, str] = {}
    for stratum, families in sorted(by_stratum.items()):
        ordered = sorted(
            families,
            key=lambda item: hashlib.sha256(
                f"{seed}\0{stratum[0]}\0{stratum[1]}\0{item[0]}".encode("utf-8")
            ).digest(),
        )
        target = round(sum(len(members) for _, members in ordered) * calibration_fraction)
        selected = 0
        for index, (family, members) in enumerate(ordered):
            families_left = len(ordered) - index - 1
            use_calibration = selected < target and not (
                families_left == 0 and not any(
                    side == "validation"
                    for existing, side in family_side.items()
                    if existing in {name for name, _ in ordered}
                )
            )
            side = "calibration" if use_calibration else "validation"
            family_side[family] = side
            if use_calibration:
                calibration.extend(members)
                selected += len(members)
            else:
                validation.extend(members)

    calibration_families = {
        item.record.family_id or item.record.record_id for item in calibration
    }
    validation_families = {
        item.record.family_id or item.record.record_id for item in validation
    }
    if calibration_families & validation_families:
        raise AssertionError("one family was assigned to both calibration partitions")
    return calibration, validation


def calibrate_alias_rules(
    observations: list[RouteObservation],
    *,
    target_precision: float,
    min_observed_count: int = 3,
) -> dict[str, AliasRule]:
    """Gate fixed, pre-existing alias rules on the untouched held-out set.

    Unlike similarity thresholds, alias rules are not tuned by this function;
    they were version-controlled before evaluation. Their full held-out route
    quality is therefore an unbiased fixed-rule check rather than a training
    metric.
    """
    fields = sorted({item.record.field for item in observations})
    rules: dict[str, AliasRule] = {}
    for field in fields:
        observed = [
            item for item in observations
            if item.record.field == field and item.route == "alias"
        ]
        precision = (
            sum(item.correct for item in observed) / len(observed)
            if observed else 0.0
        )
        enabled = (
            len(observed) >= min_observed_count
            and precision >= target_precision
        )
        rules[field] = AliasRule(
            enabled=enabled,
            observed_precision=precision,
            observed_count=len(observed),
            reason=(
                "Enabled: the fixed approved-alias route met the target on the held-out set."
                if enabled else
                "Disabled for automatic use: insufficient held-out volume or precision; aliases remain classifier evidence."
            ),
        )
    return rules


def _accepted(
    observations: Iterable[RouteObservation],
    *,
    min_score: float,
    min_margin: float,
    min_agreement: float,
    min_support: int,
) -> list[RouteObservation]:
    return [
        observation
        for observation in observations
        if observation.route == "similarity"
        and observation.evidence.score >= min_score
        and observation.evidence.margin >= min_margin
        and observation.evidence.agreement >= min_agreement
        and observation.evidence.support >= min_support
    ]


def _quality(
    accepted: list[RouteObservation],
    population: list[RouteObservation],
) -> tuple[float, float, int]:
    precision = (
        sum(observation.correct for observation in accepted) / len(accepted)
        if accepted else 0.0
    )
    coverage = len(accepted) / len(population) if population else 0.0
    return precision, coverage, len(accepted)


def _candidate_thresholds() -> Iterable[tuple[float, float, float, int]]:
    for score_step in range(55, 101):
        for margin in (0.0, 0.03, 0.06, 0.09, 0.12, 0.18):
            for agreement in (0.67, 0.80, 1.0):
                for support in (1, 2):
                    yield score_step / 100.0, margin, agreement, support


def calibrate_similarity_rules(
    calibration: list[RouteObservation],
    validation: list[RouteObservation],
    *,
    target_precision: float,
    min_calibration_count: int = 10,
    min_validation_count: int = 5,
) -> dict[str, SimilarityRule]:
    fields = sorted({item.record.field for item in calibration + validation})
    rules: dict[str, SimilarityRule] = {}
    for field in fields:
        cal_field = [item for item in calibration if item.record.field == field]
        val_field = [item for item in validation if item.record.field == field]
        qualifying: list[tuple[Any, ...]] = []
        for score, margin, agreement, support in _candidate_thresholds():
            accepted = _accepted(
                cal_field,
                min_score=score,
                min_margin=margin,
                min_agreement=agreement,
                min_support=support,
            )
            precision, coverage, count = _quality(accepted, cal_field)
            if count >= min_calibration_count and precision >= target_precision:
                qualifying.append((
                    -coverage,
                    -precision,
                    -count,
                    score,
                    margin,
                    agreement,
                    support,
                ))
        if not qualifying:
            rules[field] = SimilarityRule(
                enabled=False,
                min_score=1.0,
                min_margin=1.0,
                min_agreement=1.0,
                min_support=2,
                calibration_precision=0.0,
                calibration_coverage=0.0,
                calibration_count=0,
                validation_precision=0.0,
                validation_coverage=0.0,
                validation_count=0,
                reason="No calibration threshold met the precision/sample requirements.",
            )
            continue

        _, _, _, score, margin, agreement, support = min(qualifying)
        cal_accepted = _accepted(
            cal_field,
            min_score=score,
            min_margin=margin,
            min_agreement=agreement,
            min_support=support,
        )
        val_accepted = _accepted(
            val_field,
            min_score=score,
            min_margin=margin,
            min_agreement=agreement,
            min_support=support,
        )
        cal_precision, cal_coverage, cal_count = _quality(cal_accepted, cal_field)
        val_precision, val_coverage, val_count = _quality(val_accepted, val_field)
        enabled = val_count >= min_validation_count and val_precision >= target_precision
        reason = (
            "Enabled: calibration-selected threshold met the target on the "
            "family-disjoint validation partition."
            if enabled else
            "Disabled: calibration-selected threshold lacked validation volume "
            "or failed the target precision."
        )
        rules[field] = SimilarityRule(
            enabled=enabled,
            min_score=score,
            min_margin=margin,
            min_agreement=agreement,
            min_support=support,
            calibration_precision=cal_precision,
            calibration_coverage=cal_coverage,
            calibration_count=cal_count,
            validation_precision=val_precision,
            validation_coverage=val_coverage,
            validation_count=val_count,
            reason=reason,
        )
    return rules


def _route_metrics(observations: Iterable[RouteObservation]) -> dict[str, dict[str, Any]]:
    by_route: dict[str, list[RouteObservation]] = defaultdict(list)
    for item in observations:
        by_route[item.route].append(item)
    result = {
        route: {
            "count": len(items),
            "correct": sum(item.correct for item in items),
            "precision": sum(item.correct for item in items) / len(items),
            "by_field": {
                field: {
                    "count": len(field_items),
                    "correct": sum(item.correct for item in field_items),
                    "precision": sum(item.correct for item in field_items) / len(field_items),
                }
                for field in sorted({item.record.field for item in items})
                if (field_items := [item for item in items if item.record.field == field])
            },
        }
        for route, items in sorted(by_route.items())
        if items
    }
    return result


def _policy_metrics(
    observations: list[RouteObservation],
    alias_rules: dict[str, AliasRule],
    rules: dict[str, SimilarityRule],
) -> dict[str, Any]:
    automatic: list[RouteObservation] = []
    route_counts: Counter[str] = Counter()
    for item in observations:
        accepted = item.route == "exact"
        if item.route == "alias":
            alias_rule = alias_rules.get(item.record.field)
            accepted = bool(alias_rule and alias_rule.enabled)
        if item.route == "similarity":
            rule = rules.get(item.record.field)
            accepted = bool(rule and rule.accepts(item.evidence))
        if accepted:
            automatic.append(item)
            route_counts[item.route] += 1
    total = len(observations)
    correct = sum(item.correct for item in automatic)
    by_field: dict[str, dict[str, Any]] = {}
    for field in sorted({item.record.field for item in observations}):
        population = [item for item in observations if item.record.field == field]
        selected = [item for item in automatic if item.record.field == field]
        by_field[field] = {
            "total": len(population),
            "automatic": len(selected),
            "correct": sum(item.correct for item in selected),
            "precision": (
                sum(item.correct for item in selected) / len(selected)
                if selected else None
            ),
            "coverage": len(selected) / len(population) if population else 0.0,
        }
    return {
        "total": total,
        "automatic": len(automatic),
        "correct": correct,
        "precision": correct / len(automatic) if automatic else 0.0,
        "coverage": len(automatic) / total if total else 0.0,
        "remaining_for_classifier_or_review": total - len(automatic),
        "automatic_by_route": dict(sorted(route_counts.items())),
        "by_field": by_field,
    }


def ambiguity_report(records: Iterable[EvaluationRecord]) -> dict[str, Any]:
    families: dict[str, list[EvaluationRecord]] = defaultdict(list)
    for record in records:
        if record.ambiguous:
            families[record.family_id].append(record)
    rows: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    for family_id, members in sorted(families.items()):
        labels = sorted({member.expected_value for member in members})
        countries = sorted({member.country or "[GLOBAL]" for member in members})
        normalized = {normalize_value(member.raw_value) for member in members}
        if len(normalized) == 1 and len(countries) > 1:
            category = "country_or_context_override"
        elif "Other / Unclassified" in labels:
            category = "catch_all_boundary"
        else:
            category = "near_variant_label_disagreement"
        category_counts[category] += len(members)
        rows.append({
            "family_id": family_id,
            "field": members[0].field,
            "category": category,
            "record_count": len(members),
            "labels": labels,
            "countries": countries,
            "values": sorted({member.raw_value for member in members})[:20],
            "priority": (
                "high" if category == "near_variant_label_disagreement"
                else "medium"
            ),
        })
    rows.sort(key=lambda row: (
        0 if row["priority"] == "high" else 1,
        -row["record_count"],
        row["field"],
        row["family_id"],
    ))
    return {
        "ambiguous_records": sum(len(members) for members in families.values()),
        "ambiguous_families": len(families),
        "records_by_category": dict(sorted(category_counts.items())),
        "note": (
            "These are heuristic review categories, not claims that the approved "
            "answers are wrong. Country/context overrides may be legitimate."
        ),
        "families": rows,
    }


def calibrate_automation(
    records: list[EvaluationRecord],
    reference_lookup_path: Path,
    *,
    source_lookup_sha256: str,
    target_precision: float = 0.92,
    split_seed: int = 20260730,
) -> tuple[AutomationPolicy, dict[str, Any], dict[str, Any]]:
    observations = observe_routes(records, load_reference_lookups(reference_lookup_path))
    calibration, validation = split_observations(observations, seed=split_seed)
    rules = calibrate_similarity_rules(
        calibration,
        validation,
        target_precision=target_precision,
    )
    alias_rules = calibrate_alias_rules(
        observations,
        target_precision=target_precision,
    )
    policy = AutomationPolicy(
        schema_version=1,
        target_precision=target_precision,
        source_lookup_sha256=source_lookup_sha256,
        split_seed=split_seed,
        alias_rules=alias_rules,
        similarity_rules=rules,
    )
    report = {
        "target_precision": target_precision,
        "method": (
            "Thresholds selected on 60% of held-out value families and accepted "
            "only when they also meet the target on the remaining 40%."
        ),
        "calibration_records": len(calibration),
        "validation_records": len(validation),
        "family_overlap": 0,
        "route_quality_all_heldout": _route_metrics(observations),
        "calibration_policy": _policy_metrics(calibration, alias_rules, rules),
        "validation_policy": _policy_metrics(validation, alias_rules, rules),
        "alias_rules": {
            field: asdict(rule) for field, rule in sorted(alias_rules.items())
        },
        "similarity_rules": {
            field: asdict(rule) for field, rule in sorted(rules.items())
        },
        "limitations": [
            "Exact lookup coverage is intentionally near zero because related families are held out.",
            "Alias rules are version-controlled approved rules, but their observed route quality is reported separately.",
            "No Claude or real semantic-embedding accuracy is measured by this offline calibration.",
            "Small fields remain disabled when validation evidence is insufficient.",
        ],
    }
    return policy, report, ambiguity_report(records)
