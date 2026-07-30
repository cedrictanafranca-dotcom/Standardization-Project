from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluation.approaches import MockClassifier, run_predictor
from evaluation.dataset import (
    annotate_families,
    build_dataset,
    split_by_family,
)
from evaluation.families import build_family_map
from evaluation.metrics import score_predictions
from evaluation.models import EvaluationRecord


def record(
    record_id: str,
    field: str,
    raw: str,
    expected: str,
    country: str = "",
) -> EvaluationRecord:
    return EvaluationRecord(record_id, field, raw, expected, country)


class FamilyTests(unittest.TestCase):
    def test_close_variants_and_countries_share_family(self) -> None:
        records = [
            record("1", "position", "Managing Director", "Executive", "Canada"),
            record("2", "position", "MANAGING-DIRECTOR", "Board", "UK"),
            record("3", "position", "Owner", "Owner"),
        ]
        families = build_family_map(records)
        self.assertEqual(
            families[("position", "Managing Director")],
            families[("position", "MANAGING-DIRECTOR")],
        )
        self.assertNotEqual(
            families[("position", "Managing Director")],
            families[("position", "Owner")],
        )

    def test_split_has_no_family_leakage_and_is_repeatable(self) -> None:
        records = annotate_families([
            record("1", "f", "Director", "A", "US"),
            record("2", "f", "DIRECTOR", "B", "UK"),
            record("3", "f", "Owner", "C", "US"),
            record("4", "f", "Partner", "C", "CA"),
            record("5", "g", "Active", "Active"),
            record("6", "g", "Inactive", "Inactive"),
        ])
        ref_a, test_a, manifest_a = split_by_family(records, 0.34, seed=7)
        ref_b, test_b, manifest_b = split_by_family(records, 0.34, seed=7)
        self.assertEqual([r.record_id for r in test_a], [r.record_id for r in test_b])
        self.assertEqual(manifest_a, manifest_b)
        self.assertFalse(
            {r.family_id for r in ref_a} & {r.family_id for r in test_a}
        )
        director_side = {
            "test" if r in test_a else "reference"
            for r in records if "director" in r.raw_value.casefold()
        }
        self.assertEqual(len(director_side), 1)


class DatasetTests(unittest.TestCase):
    def test_builder_removes_heldout_families_from_reference_lookup(self) -> None:
        lookup = {
            "f": {
                "consistent": {
                    "Director": "A",
                    "DIRECTOR": "A",
                    "Owner": "B",
                    "Partner": "B",
                    "Trustee": "C",
                },
                "by_country": {
                    "UK": {"Director": "C"},
                    "CA": {"Proprietor": "B"},
                },
            },
            "g": {
                "consistent": {"Active": "Active", "Inactive": "Inactive"},
                "by_country": {},
            },
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "lookup.json"
            source.write_text(json.dumps(lookup), encoding="utf-8")
            output = root / "out"
            manifest = build_dataset(source, output, 0.35, seed=3)
            heldout = [
                json.loads(line)
                for line in (output / "heldout.jsonl").read_text().splitlines()
            ]
            reference = json.loads(
                (output / "reference_lookup.json").read_text()
            )
            heldout_raw = {(row["field"], row["raw_value"]) for row in heldout}
            reference_raw = set()
            for field, field_data in reference.items():
                reference_raw.update(
                    (field, raw) for raw in field_data["consistent"]
                )
                for country_map in field_data["by_country"].values():
                    reference_raw.update((field, raw) for raw in country_map)
            self.assertFalse(heldout_raw & reference_raw)
            self.assertEqual(manifest["family_overlap"], 0)


class MetricsTests(unittest.TestCase):
    def test_mock_classifiers_produce_all_required_metrics(self) -> None:
        records = [
            EvaluationRecord("1", "f", "a", "A", frequency_band="common"),
            EvaluationRecord("2", "f", "b", "B", country="UK", ambiguous=True),
            EvaluationRecord("3", "g", "c", "Other / Unclassified"),
        ]
        answers = {"1": "A", "2": "WRONG", "3": "Other / Unclassified"}
        mock = MockClassifier(
            name="prompt-only-mock",
            classifier=lambda item: answers[item.record_id],
            confidence="HIGH",
            route="prompt-only",
            api_bound=True,
        )
        predictions = run_predictor(records, mock)
        report = score_predictions(records, predictions, mock.name)
        self.assertAlmostEqual(report["overall_accuracy"], 2 / 3)
        self.assertEqual(report["incorrect_high"]["count"], 1)
        self.assertAlmostEqual(report["catch_all_rate"], 1 / 3)
        self.assertEqual(report["review_rate"], 0)
        self.assertEqual(report["predictive_coverage"], 0)
        self.assertEqual(report["api_bound_values"]["count"], 3)
        self.assertIn("f", report["accuracy_by_field"])
        self.assertIn("f::A", report["accuracy_by_category"])
        self.assertIn("UK", report["accuracy_by_country"])

    def test_predictive_mock_tracks_coverage_without_api(self) -> None:
        records = [EvaluationRecord("1", "f", "a", "A")]
        mock = MockClassifier(
            name="predictive-mock",
            classifier=lambda item: item.expected_value,
            confidence="MEDIUM",
            route="predictive",
            api_bound=False,
        )
        report = score_predictions(records, run_predictor(records, mock), mock.name)
        self.assertEqual(report["predictive_coverage"], 1)
        self.assertEqual(report["api_bound_values"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
