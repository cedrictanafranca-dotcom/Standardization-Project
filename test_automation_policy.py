"""Offline tests for measured automation policy enforcement."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import standardize_file as sf  # noqa: E402
from automation_policy import (  # noqa: E402
    AliasRule,
    AutomationPolicy,
    SimilarityEvidence,
    SimilarityRule,
)
from master_lookup import FieldLookup  # noqa: E402


CANONICAL = [
    "Board Member",
    "Director",
    "Executive Management",
    "Owner / Controller",
    "Authorized Representative",
    "Other / Unclassified",
]


class ScriptedClient:
    name = "SCRIPTED"

    def __init__(self, response: str = "") -> None:
        self.response = response
        self.calls = 0

    def complete(self, system_prompt: str, user_message: str) -> str:
        self.calls += 1
        if not self.response:
            raise AssertionError("classifier should not have been called")
        return self.response


def _policy(*, aliases: bool, similarity: bool) -> AutomationPolicy:
    return AutomationPolicy(
        schema_version=1,
        target_precision=0.92,
        source_lookup_sha256="test",
        split_seed=1,
        alias_rules={
            "positions_designations": AliasRule(
                enabled=aliases,
                observed_precision=1.0 if aliases else 0.80,
                observed_count=20,
                reason="test alias rule",
            )
        },
        similarity_rules={
            "positions_designations": SimilarityRule(
                enabled=similarity,
                min_score=0.50,
                min_margin=0.0,
                min_agreement=0.50,
                min_support=1,
                calibration_precision=0.95,
                calibration_coverage=0.50,
                calibration_count=20,
                validation_precision=0.94,
                validation_coverage=0.40,
                validation_count=10,
                reason="test similarity rule",
            )
        },
    )


class AutomationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_lookup = sf._MASTER_LOOKUP

    def tearDown(self) -> None:
        sf._MASTER_LOOKUP = self.original_lookup

    def test_rule_enforces_every_threshold(self) -> None:
        rule = _policy(aliases=False, similarity=True).similarity_rules[
            "positions_designations"
        ]
        self.assertTrue(rule.accepts(SimilarityEvidence(
            predicted_value="Director",
            score=0.80,
            margin=0.20,
            agreement=1.0,
            support=2,
        )))
        self.assertFalse(rule.accepts(SimilarityEvidence(
            predicted_value="Director",
            score=0.49,
            margin=0.20,
            agreement=1.0,
            support=2,
        )))

    def test_unvalidated_alias_is_sent_to_classifier(self) -> None:
        sf._MASTER_LOOKUP = {
            "positions_designations": FieldLookup("positions_designations")
        }
        client = ScriptedClient(
            "1. Executive Management | HIGH\n[Total: 1 of 1 mapped]"
        )
        result, stats = sf.standardize_dataframe(
            pd.DataFrame({"Value": ["C.E.O."]}),
            "Value",
            "taxonomy",
            client,
            field_key="positions_designations",
            canonical_values=CANONICAL,
            automation_policy=_policy(aliases=False, similarity=False),
        )
        self.assertEqual(client.calls, 1)
        self.assertEqual(stats.alias_matches, 0)
        self.assertEqual(stats.alias_deferred, 1)
        self.assertEqual(
            result.loc[0, sf.STANDARDIZED_COLUMN], "Executive Management"
        )

    def test_validated_similarity_rule_avoids_classifier(self) -> None:
        sf._MASTER_LOOKUP = {
            "positions_designations": FieldLookup(
                field_key="positions_designations",
                consistent={"Managing Director": "Executive Management"},
            )
        }
        result, stats = sf.standardize_dataframe(
            pd.DataFrame({"Value": ["Managing Directr"]}),
            "Value",
            "taxonomy",
            ScriptedClient(),
            field_key="positions_designations",
            canonical_values=CANONICAL,
            alias_matcher=None,
            automation_policy=_policy(aliases=False, similarity=True),
        )
        self.assertEqual(stats.similarity_predictions, 1)
        self.assertEqual(stats.batches, 0)
        self.assertEqual(
            result.loc[0, sf.STANDARDIZED_COLUMN], "Executive Management"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
