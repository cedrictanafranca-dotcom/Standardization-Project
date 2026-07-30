"""Deterministic tests for offline automation calibration."""

from __future__ import annotations

import unittest

from evaluation.automation import (
    RouteObservation,
    ambiguity_report,
    calibrate_alias_rules,
    calibrate_similarity_rules,
    split_observations,
)
from evaluation.models import EvaluationRecord
from automation_policy import SimilarityEvidence


def _observation(
    index: int,
    *,
    field: str = "test_field",
    family: str | None = None,
    route: str = "similarity",
    correct: bool = True,
    score: float = 0.90,
) -> RouteObservation:
    expected = "A"
    predicted = expected if correct else "B"
    return RouteObservation(
        EvaluationRecord(
            record_id=f"r{index}",
            field=field,
            raw_value=f"value {index}",
            expected_value=expected,
            family_id=family or f"family-{index}",
        ),
        route,
        predicted,
        SimilarityEvidence(
            predicted_value=predicted,
            score=score,
            margin=0.20,
            agreement=1.0,
            support=2,
        ),
    )


class AutomationCalibrationTests(unittest.TestCase):
    def test_partition_never_splits_a_family(self) -> None:
        observations = [
            _observation(1, family="shared"),
            _observation(2, family="shared"),
            *[_observation(index) for index in range(3, 20)],
        ]
        calibration, validation = split_observations(observations, seed=7)
        cal_families = {item.record.family_id for item in calibration}
        val_families = {item.record.family_id for item in validation}
        self.assertFalse(cal_families & val_families)
        self.assertTrue(calibration)
        self.assertTrue(validation)

    def test_similarity_rule_requires_independent_validation(self) -> None:
        calibration = [_observation(index) for index in range(20)]
        validation = [_observation(index + 100) for index in range(10)]
        rules = calibrate_similarity_rules(
            calibration,
            validation,
            target_precision=0.92,
            min_calibration_count=5,
            min_validation_count=5,
        )
        self.assertTrue(rules["test_field"].enabled)

        failed_validation = [
            _observation(index + 200, correct=index < 8)
            for index in range(10)
        ]
        rules = calibrate_similarity_rules(
            calibration,
            failed_validation,
            target_precision=0.92,
            min_calibration_count=5,
            min_validation_count=5,
        )
        self.assertFalse(rules["test_field"].enabled)

    def test_fixed_alias_route_uses_heldout_precision(self) -> None:
        aliases = [
            _observation(index, route="alias", correct=index < 9)
            for index in range(10)
        ]
        rules = calibrate_alias_rules(
            aliases,
            target_precision=0.92,
            min_observed_count=3,
        )
        self.assertFalse(rules["test_field"].enabled)

    def test_ambiguity_report_separates_country_and_boundary_cases(self) -> None:
        records = [
            EvaluationRecord(
                "a", "positions_designations", "Director", "Director",
                country="France", family_id="f1", ambiguous=True,
            ),
            EvaluationRecord(
                "b", "positions_designations", "Director", "Board Member",
                country="United Kingdom", family_id="f1", ambiguous=True,
            ),
            EvaluationRecord(
                "c", "business_legal_form", "Odd Company", "Company",
                family_id="f2", ambiguous=True,
            ),
            EvaluationRecord(
                "d", "business_legal_form", "Odd Co", "Other / Unclassified",
                family_id="f2", ambiguous=True,
            ),
        ]
        report = ambiguity_report(records)
        self.assertEqual(report["ambiguous_records"], 4)
        self.assertEqual(
            report["records_by_category"]["country_or_context_override"], 2
        )
        self.assertEqual(report["records_by_category"]["catch_all_boundary"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
