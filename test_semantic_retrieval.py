"""Deterministic quality and performance tests for semantic retrieval."""

from __future__ import annotations

import hashlib
import sys
import time
import unittest
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from semantic_retrieval import (  # noqa: E402
    ApprovedMapping,
    RetrievalConfig,
    SemanticRetriever,
)


class FakeEmbeddingProvider:
    """Deterministic semantic stand-in with observable batching/caching."""

    model_id = "fake-multilingual-v1"

    def __init__(self, concepts: dict[str, Sequence[float]] | None = None) -> None:
        self.concepts = {
            key.casefold(): tuple(value) for key, value in (concepts or {}).items()
        }
        self.calls: list[tuple[str, ...]] = []

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        self.calls.append(tuple(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> tuple[float, ...]:
        known = self.concepts.get(text.casefold())
        if known is not None:
            return known
        digest = hashlib.sha256(text.casefold().encode("utf-8")).digest()
        return tuple((digest[index] / 127.5) - 1.0 for index in range(8))


class SemanticRetrievalTests(unittest.TestCase):
    def test_multilingual_and_transliterated_variants_rank_together(self) -> None:
        concepts = {
            "Управляющий директор": (1.0, 0.0, 0.0),
            "upravlyayushchiy direktor": (1.0, 0.0, 0.0),
            "Geschäftsführer": (0.8, 0.6, 0.0),
            "managing director": (1.0, 0.0, 0.0),
            "Член совета директоров": (0.0, 1.0, 0.0),
        }
        retriever = SemanticRetriever(
            [
                ApprovedMapping(
                    "positions_designations",
                    "Управляющий директор",
                    "Executive Management",
                ),
                ApprovedMapping(
                    "positions_designations",
                    "Geschäftsführer",
                    "Executive Management",
                ),
                ApprovedMapping(
                    "positions_designations",
                    "Член совета директоров",
                    "Board Member",
                ),
            ],
            FakeEmbeddingProvider(concepts),
        )

        transliterated = retriever.retrieve(
            "upravlyayushchiy direktor", field_key="positions_designations"
        )
        multilingual = retriever.retrieve(
            "managing director", field_key="positions_designations"
        )

        self.assertEqual(
            transliterated.evidence[0].source_value, "Управляющий директор"
        )
        self.assertEqual(
            multilingual.evidence[0].source_value, "Управляющий директор"
        )
        self.assertEqual(
            multilingual.evidence[0].label, "Executive Management"
        )

    def test_lexical_signal_is_preserved_in_hybrid_ranking(self) -> None:
        provider = FakeEmbeddingProvider(
            {
                "managing directr": (0.0, 1.0),
                "managing director": (1.0, 0.0),
                "general manager": (0.0, 1.0),
            }
        )
        retriever = SemanticRetriever(
            [
                ApprovedMapping(
                    "positions_designations",
                    "Managing Director",
                    "Executive Management",
                ),
                ApprovedMapping(
                    "positions_designations",
                    "General Manager",
                    "Executive Management",
                ),
            ],
            provider,
        )

        result = retriever.retrieve(
            "Managing Directr", field_key="positions_designations"
        )

        self.assertEqual(result.evidence[0].source_value, "Managing Director")
        self.assertGreater(result.evidence[0].lexical_score, 0.9)
        self.assertEqual(result.evidence[0].score, result.evidence[0].lexical_score)

    def test_field_and_country_isolation_with_country_override(self) -> None:
        concepts = {
            "chief executive": (1.0, 0.0),
            "CEO": (1.0, 0.0),
            "chief executive tax identifier": (1.0, 0.0),
        }
        retriever = SemanticRetriever(
            [
                ApprovedMapping(
                    "positions_designations", "CEO", "Executive Management"
                ),
                ApprovedMapping(
                    "positions_designations",
                    "CEO",
                    "Board Member",
                    "United Kingdom",
                ),
                ApprovedMapping(
                    "positions_designations", "CEO", "Director", "France"
                ),
                ApprovedMapping(
                    "brn_type",
                    "chief executive tax identifier",
                    "Tax ID Number",
                ),
            ],
            FakeEmbeddingProvider(concepts),
        )

        uk = retriever.retrieve(
            "chief executive",
            field_key="positions_designations",
            country="United Kingdom",
        )
        global_result = retriever.retrieve(
            "chief executive", field_key="positions_designations"
        )

        self.assertEqual([item.label for item in uk.evidence], ["Board Member"])
        self.assertEqual(uk.evidence[0].country, "United Kingdom")
        self.assertEqual(
            [item.label for item in global_result.evidence],
            ["Executive Management"],
        )
        self.assertTrue(all(item.field_key == "positions_designations" for item in uk.evidence))
        self.assertNotIn("France", {item.country for item in uk.evidence})

    def test_conflicting_neighbor_labels_are_explicit(self) -> None:
        concepts = {
            "managing": (1.0, 0.0, 0.0),
            "managing director": (0.99, 0.05, 0.0),
            "managing partner": (0.98, 0.08, 0.0),
            "board observer": (0.0, 1.0, 0.0),
        }
        retriever = SemanticRetriever(
            [
                ApprovedMapping(
                    "positions_designations",
                    "Managing Director",
                    "Executive Management",
                ),
                ApprovedMapping(
                    "positions_designations",
                    "Managing Partner",
                    "Owner / Controller",
                ),
                ApprovedMapping(
                    "positions_designations", "Board Observer", "Board Member"
                ),
            ],
            FakeEmbeddingProvider(concepts),
            config=RetrievalConfig(conflict_window=0.12),
        )

        result = retriever.retrieve(
            "Managing", field_key="positions_designations"
        )

        self.assertTrue(result.has_conflicts)
        self.assertNotEqual(result.conflicts[0].label, result.evidence[0].label)
        self.assertEqual(
            {result.conflicts[0].label, result.evidence[0].label},
            {"Executive Management", "Owner / Controller"},
        )

    def test_evidence_is_small_and_highly_ranked(self) -> None:
        concepts = {"query": (1.0, 0.0)}
        mappings = []
        for index in range(12):
            value = f"example {index}"
            concepts[value] = (1.0 - index * 0.01, 0.05)
            mappings.append(ApprovedMapping("field", value, f"label {index % 3}"))
        retriever = SemanticRetriever(
            mappings,
            FakeEmbeddingProvider(concepts),
            config=RetrievalConfig(max_results=4, max_per_label=2),
        )

        result = retriever.retrieve("query", field_key="field")

        self.assertEqual(len(result.evidence), 4)
        counts: dict[str, int] = {}
        for item in result.evidence:
            counts[item.label] = counts.get(item.label, 0) + 1
        self.assertLessEqual(max(counts.values()), 2)
        self.assertEqual(
            list(result.evidence),
            sorted(result.evidence, key=lambda item: item.score, reverse=True),
        )

    def test_embeddings_are_cached_by_model_and_text(self) -> None:
        provider = FakeEmbeddingProvider(
            {
                "query": (1.0, 0.0),
                "other query": (0.9, 0.1),
                "candidate": (1.0, 0.0),
            }
        )
        shared_cache: dict[str, tuple[float, ...]] = {}
        retriever = SemanticRetriever(
            [ApprovedMapping("field", "candidate", "label")],
            provider,
            embedding_cache=shared_cache,
        )

        retriever.retrieve("query", field_key="field")
        retriever.retrieve("query", field_key="field")
        retriever.retrieve("other query", field_key="field")

        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[0], ("query", "candidate"))
        self.assertEqual(provider.calls[1], ("other query",))
        self.assertEqual(len(shared_cache), 3)

    def test_reasonable_runtime_for_current_lookup_scale(self) -> None:
        provider = FakeEmbeddingProvider({"target phrase": (1.0,) * 8})
        mappings = [
            ApprovedMapping("field", f"approved mapping {index}", f"label {index % 6}")
            for index in range(4_000)
        ]
        retriever = SemanticRetriever(mappings, provider)

        started = time.perf_counter()
        result = retriever.retrieve("target phrase", field_key="field")
        elapsed = time.perf_counter() - started

        self.assertLessEqual(len(result.evidence), 4)
        self.assertLess(
            elapsed,
            3.0,
            f"4,000-candidate retrieval took {elapsed:.3f}s",
        )


if __name__ == "__main__":
    unittest.main()
