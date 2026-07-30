"""Offline integration tests for the combined accuracy-first decision path."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import standardize_file as sf  # noqa: E402
from classifier import VerificationPolicy  # noqa: E402
from embedding_providers import DeterministicHashEmbeddingProvider  # noqa: E402
from master_lookup import FieldLookup  # noqa: E402
from semantic_retrieval import (  # noqa: E402
    ApprovedMapping,
    RetrievalConfig,
    SemanticRetriever,
)


CANONICAL = [
    "Board Member",
    "Director",
    "Executive Management",
    "Owner / Controller",
    "Authorized Representative",
    "Other / Unclassified",
]


class ScriptedClient:
    name = "SCRIPTED OFFLINE CLIENT"

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.messages: list[str] = []

    def complete(self, system_prompt: str, user_message: str) -> str:
        self.messages.append(user_message)
        if not self.responses:
            raise AssertionError("classifier should not have been called")
        return self.responses.pop(0)


class ConstantEmbeddingProvider:
    model_id = "constant-offline-test"

    def embed(self, texts: Sequence[str]) -> list[tuple[float, float]]:
        return [(1.0, 0.0) for _ in texts]


class IntegratedRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_lookup = sf._MASTER_LOOKUP
        self.original_embedding_provider = sf._EMBEDDING_PROVIDER
        self.original_semantic_retriever = sf._SEMANTIC_RETRIEVER

    def tearDown(self) -> None:
        sf._MASTER_LOOKUP = self.original_lookup
        sf._EMBEDDING_PROVIDER = self.original_embedding_provider
        sf._SEMANTIC_RETRIEVER = self.original_semantic_retriever

    def _run(self, value: str, client, **kwargs):
        return sf.standardize_dataframe(
            pd.DataFrame({"Value": [value]}),
            "Value",
            "offline taxonomy",
            client,
            field_key="positions_designations",
            canonical_values=CANONICAL,
            **kwargs,
        )

    def test_exact_lookup_wins_before_every_other_route(self) -> None:
        sf._MASTER_LOOKUP = {
            "positions_designations": FieldLookup(
                field_key="positions_designations",
                consistent={"CEO": "Director"},
            )
        }
        result, stats = self._run("CEO", ScriptedClient())
        self.assertEqual(result.loc[0, sf.STANDARDIZED_COLUMN], "Director")
        self.assertEqual(stats.lookup_hits, 1)
        self.assertEqual(stats.alias_matches, 0)
        self.assertEqual(stats.batches, 0)

    def test_approved_alias_is_the_only_new_automatic_route(self) -> None:
        sf._MASTER_LOOKUP = {
            "positions_designations": FieldLookup("positions_designations")
        }
        result, stats = self._run("C.E.O.", ScriptedClient())
        self.assertEqual(
            result.loc[0, sf.STANDARDIZED_COLUMN], "Executive Management"
        )
        self.assertEqual(stats.alias_matches, 1)
        self.assertEqual(stats.batches, 0)

    def test_modifier_case_is_classified_but_forced_to_review(self) -> None:
        sf._MASTER_LOOKUP = {
            "positions_designations": FieldLookup("positions_designations")
        }
        client = ScriptedClient(
            "1. Executive Management | HIGH\n[Total: 1 of 1 mapped]"
        )
        result, stats = self._run("Acting CEO", client)
        self.assertEqual(stats.alias_reviews, 1)
        self.assertEqual(stats.batches, 1)
        self.assertEqual(
            result.loc[0, sf.STANDARDIZED_COLUMN], "Executive Management"
        )
        self.assertTrue(result.loc[0, sf.NEEDS_REVIEW_COLUMN])
        self.assertIn(
            "meaning-changing modifier",
            result.loc[0, sf.REVIEW_REASON_COLUMN],
        )
        self.assertIn('"safety_warnings"', client.messages[0])

    def test_semantic_conflict_is_evidence_only_and_forced_to_review(self) -> None:
        sf._MASTER_LOOKUP = {
            "positions_designations": FieldLookup("positions_designations")
        }
        retriever = SemanticRetriever(
            [
                ApprovedMapping(
                    "positions_designations", "Managing Director", "Executive Management"
                ),
                ApprovedMapping(
                    "positions_designations", "Board Director", "Board Member"
                ),
            ],
            ConstantEmbeddingProvider(),
            config=RetrievalConfig(min_score=0.0, conflict_window=1.0),
        )
        client = ScriptedClient(
            "1. Executive Management | HIGH\n[Total: 1 of 1 mapped]"
        )
        result, stats = self._run(
            "Novel Director Title",
            client,
            alias_matcher=None,
            semantic_retriever=retriever,
        )
        self.assertEqual(stats.semantic_retrievals, 1)
        self.assertEqual(stats.similarity_predictions, 0)
        self.assertEqual(stats.batches, 1)
        self.assertTrue(result.loc[0, sf.NEEDS_REVIEW_COLUMN])
        self.assertIn("competing nearby", result.loc[0, sf.REVIEW_REASON_COLUMN])
        self.assertIn('"evidence_status":"CONFLICTING"', client.messages[0])

    def test_legacy_similarity_prediction_is_off_by_default(self) -> None:
        sf._MASTER_LOOKUP = {
            "positions_designations": FieldLookup(
                field_key="positions_designations",
                consistent={"Managing Director": "Executive Management"},
            )
        }
        client = ScriptedClient(
            "1. Executive Management | HIGH\n[Total: 1 of 1 mapped]"
        )
        _, stats = self._run(
            "MANAGING DIRECTOR",
            client,
            alias_matcher=None,
        )
        self.assertEqual(stats.similarity_predictions, 0)
        self.assertEqual(stats.retrieval_assisted, 1)
        self.assertEqual(stats.batches, 1)

    def test_classifier_verifier_disagreement_routes_to_review(self) -> None:
        sf._MASTER_LOOKUP = {
            "positions_designations": FieldLookup("positions_designations")
        }
        first = ScriptedClient(
            "1. Executive Management | MEDIUM | Reason: uncommon title\n"
            "[Total: 1 of 1 mapped]"
        )
        verifier = ScriptedClient(
            "1. Board Member | HIGH\n[Total: 1 of 1 mapped]"
        )
        result, stats = self._run(
            "Uncommon Leadership Title",
            first,
            alias_matcher=None,
            verification_policy=VerificationPolicy(),
            verification_client=verifier,
        )
        self.assertEqual(stats.verification_reviews, 1)
        self.assertTrue(result.loc[0, sf.NEEDS_REVIEW_COLUMN])
        self.assertIn("disagreement", result.loc[0, sf.REVIEW_REASON_COLUMN])

    def test_offline_embedding_provider_is_stable_and_local(self) -> None:
        provider = DeterministicHashEmbeddingProvider()
        first = provider.embed(["Managing Director"])[0]
        second = provider.embed(["Managing Director"])[0]
        self.assertEqual(first, second)
        self.assertIn("not-for-production", provider.model_id)

    def test_embedding_provider_can_be_injected_and_disabled(self) -> None:
        sf._MASTER_LOOKUP = {
            "positions_designations": FieldLookup(
                field_key="positions_designations",
                consistent={"Managing Director": "Executive Management"},
            )
        }
        configured = sf.configure_embedding_provider(
            DeterministicHashEmbeddingProvider()
        )
        self.assertIsNotNone(configured)
        self.assertTrue(
            configured.retrieve(
                "Managing Directr",
                field_key="positions_designations",
            ).evidence
        )
        self.assertIsNone(sf.configure_embedding_provider(None))
        self.assertIsNone(sf._SEMANTIC_RETRIEVER)


if __name__ == "__main__":
    unittest.main(verbosity=2)
