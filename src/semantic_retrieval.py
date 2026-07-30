"""Accuracy-first hybrid retrieval over approved standardization mappings.

This module deliberately returns evidence rather than a classification.  The
caller (Claude today, a decision engine later) remains responsible for choosing
a canonical label.

The embedding dependency is inverted behind :class:`EmbeddingProvider`.  This
keeps model choice, hosting, downloads, and network access outside the retrieval
component and makes tests deterministic.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, MutableMapping, Protocol, Sequence, runtime_checkable


Vector = tuple[float, ...]


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Minimal interface implemented by local or hosted embedding adapters."""

    @property
    def model_id(self) -> str:
        """Stable identifier used to isolate cached vectors between models."""

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Return one numeric vector for every input text, in input order."""


@dataclass(frozen=True)
class ApprovedMapping:
    """One approved source-value to canonical-label mapping."""

    field_key: str
    source_value: str
    label: str
    country: str = ""


@dataclass(frozen=True)
class RankedEvidence:
    """One ranked mapping with auditable component scores."""

    field_key: str
    source_value: str
    label: str
    country: str
    semantic_score: float
    lexical_score: float
    score: float


@dataclass(frozen=True)
class NeighborConflict:
    """A different label found within the top result's score neighborhood."""

    label: str
    best_score: float
    evidence: tuple[RankedEvidence, ...]


@dataclass(frozen=True)
class RetrievalResult:
    """Bounded evidence and any competing labels near the best result."""

    query: str
    field_key: str
    country: str
    evidence: tuple[RankedEvidence, ...]
    conflicts: tuple[NeighborConflict, ...]

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)


@dataclass(frozen=True)
class RetrievalConfig:
    """Scoring and evidence-volume controls."""

    semantic_weight: float = 0.70
    lexical_weight: float = 0.30
    min_score: float = 0.40
    max_results: int = 4
    max_per_label: int = 2
    conflict_window: float = 0.08
    conflict_evidence_limit: int = 2

    def __post_init__(self) -> None:
        if self.semantic_weight < 0 or self.lexical_weight < 0:
            raise ValueError("Similarity weights cannot be negative")
        if self.semantic_weight + self.lexical_weight <= 0:
            raise ValueError("At least one similarity weight must be positive")
        if not 0 <= self.min_score <= 1:
            raise ValueError("min_score must be between 0 and 1")
        if self.max_results < 1 or self.max_per_label < 1:
            raise ValueError("Evidence limits must be positive")
        if not 0 <= self.conflict_window <= 1:
            raise ValueError("conflict_window must be between 0 and 1")
        if self.conflict_evidence_limit < 1:
            raise ValueError("conflict_evidence_limit must be positive")


class SemanticRetriever:
    """Retrieve small, relevant hybrid evidence sets from approved mappings.

    Country-specific mappings for the requested country replace global entries
    having the same normalized source value.  Mappings belonging to other
    countries are never considered.  If no country is supplied, only global
    mappings are eligible.
    """

    def __init__(
        self,
        mappings: Iterable[ApprovedMapping],
        embedding_provider: EmbeddingProvider,
        *,
        config: RetrievalConfig | None = None,
        embedding_cache: MutableMapping[str, Vector] | None = None,
    ) -> None:
        self._mappings = tuple(mappings)
        self._provider = embedding_provider
        self._config = config or RetrievalConfig()
        self._embedding_cache = embedding_cache if embedding_cache is not None else {}
        self._validate_mappings()

    def retrieve(
        self,
        query: str,
        *,
        field_key: str,
        country: str = "",
    ) -> RetrievalResult:
        """Return ranked evidence; never infer or return a classification."""
        clean_query = _collapse(query)
        clean_country = _collapse(country)
        if not clean_query:
            return RetrievalResult(clean_query, field_key, clean_country, (), ())

        candidates = self._eligible_mappings(field_key, clean_country)
        if not candidates:
            return RetrievalResult(clean_query, field_key, clean_country, (), ())

        texts = [mapping.source_value for mapping in candidates]
        vectors = self._vectors_for([clean_query, *texts])
        query_vector = vectors[0]
        query_lexical = _lexical_key(clean_query)

        ranked: list[RankedEvidence] = []
        for mapping, vector in zip(candidates, vectors[1:]):
            semantic = _bounded_cosine(query_vector, vector)
            lexical = _lexical_score(query_lexical, _lexical_key(mapping.source_value))
            weighted = (
                self._config.semantic_weight * semantic
                + self._config.lexical_weight * lexical
            ) / (self._config.semantic_weight + self._config.lexical_weight)
            # Preserve the existing lexical signal when an embedding model has a
            # weak or surprising result for a near-identical spelling variant.
            combined = max(lexical, weighted)
            if combined >= self._config.min_score:
                ranked.append(
                    RankedEvidence(
                        field_key=mapping.field_key,
                        source_value=mapping.source_value,
                        label=mapping.label,
                        country=mapping.country,
                        semantic_score=semantic,
                        lexical_score=lexical,
                        score=combined,
                    )
                )

        ranked.sort(key=_rank_key)
        evidence = self._bounded_evidence(ranked)
        conflicts = self._neighbor_conflicts(ranked)
        return RetrievalResult(
            clean_query,
            field_key,
            clean_country,
            tuple(evidence),
            tuple(conflicts),
        )

    def _validate_mappings(self) -> None:
        for mapping in self._mappings:
            if not _collapse(mapping.field_key):
                raise ValueError("Approved mappings require a field_key")
            if not _collapse(mapping.source_value):
                raise ValueError("Approved mappings require a source_value")
            if not _collapse(mapping.label):
                raise ValueError("Approved mappings require a label")

    def _eligible_mappings(
        self, field_key: str, country: str
    ) -> list[ApprovedMapping]:
        country_key = _identity_key(country)
        global_by_source: dict[str, list[ApprovedMapping]] = {}
        country_by_source: dict[str, list[ApprovedMapping]] = {}

        # Global mappings form the fallback candidate set.
        for mapping in self._mappings:
            if mapping.field_key == field_key and not _collapse(mapping.country):
                global_by_source.setdefault(
                    _identity_key(mapping.source_value), []
                ).append(mapping)

        # The requested country's approved mappings override identical global
        # source values. Entries for every other country remain isolated.
        if country_key:
            for mapping in self._mappings:
                if (
                    mapping.field_key == field_key
                    and _identity_key(mapping.country) == country_key
                ):
                    country_by_source.setdefault(
                        _identity_key(mapping.source_value), []
                    ).append(mapping)

        selected: list[ApprovedMapping] = []
        for source_key in global_by_source.keys() | country_by_source.keys():
            selected.extend(
                country_by_source.get(source_key, global_by_source.get(source_key, []))
            )

        # Preserve same-source/different-label mappings so conflicts remain
        # explicit, while removing exact duplicate evidence rows.
        selected = list(
            {
                (
                    mapping.field_key,
                    mapping.source_value,
                    mapping.label,
                    mapping.country,
                ): mapping
                for mapping in selected
            }.values()
        )

        return sorted(
            selected,
            key=lambda item: (
                item.source_value.casefold(),
                item.label.casefold(),
                item.country.casefold(),
            ),
        )

    def _vectors_for(self, texts: Sequence[str]) -> list[Vector]:
        keys = [self._cache_key(text) for text in texts]
        missing_texts: list[str] = []
        missing_keys: list[str] = []
        seen_missing: set[str] = set()
        for key, text in zip(keys, texts):
            if key not in self._embedding_cache and key not in seen_missing:
                seen_missing.add(key)
                missing_keys.append(key)
                missing_texts.append(text)

        if missing_texts:
            embedded = self._provider.embed(missing_texts)
            if len(embedded) != len(missing_texts):
                raise ValueError(
                    "Embedding provider returned a different number of vectors "
                    "than input texts"
                )
            for key, vector in zip(missing_keys, embedded):
                clean_vector = tuple(float(value) for value in vector)
                if not clean_vector or any(not math.isfinite(v) for v in clean_vector):
                    raise ValueError("Embedding vectors must be finite and non-empty")
                self._embedding_cache[key] = clean_vector

        vectors = [self._embedding_cache[key] for key in keys]
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1:
            raise ValueError("Embedding provider returned inconsistent dimensions")
        return vectors

    def _cache_key(self, text: str) -> str:
        return f"{self._provider.model_id}\0{_collapse(text)}"

    def _bounded_evidence(
        self, ranked: Sequence[RankedEvidence]
    ) -> list[RankedEvidence]:
        selected: list[RankedEvidence] = []
        label_counts: Counter[str] = Counter()
        for item in ranked:
            if label_counts[item.label] >= self._config.max_per_label:
                continue
            selected.append(item)
            label_counts[item.label] += 1
            if len(selected) >= self._config.max_results:
                break
        return selected

    def _neighbor_conflicts(
        self, ranked: Sequence[RankedEvidence]
    ) -> list[NeighborConflict]:
        if not ranked:
            return []
        top = ranked[0]
        floor = max(self._config.min_score, top.score - self._config.conflict_window)
        by_label: dict[str, list[RankedEvidence]] = {}
        for item in ranked:
            if item.score < floor:
                break
            if item.label != top.label:
                by_label.setdefault(item.label, []).append(item)

        conflicts = [
            NeighborConflict(
                label=label,
                best_score=items[0].score,
                evidence=tuple(items[: self._config.conflict_evidence_limit]),
            )
            for label, items in by_label.items()
        ]
        conflicts.sort(key=lambda item: (-item.best_score, item.label.casefold()))
        return conflicts


def approved_mappings_from_lookups(lookups: dict[str, object]) -> list[ApprovedMapping]:
    """Adapt existing ``FieldLookup``-like objects without importing them.

    The loose input type intentionally keeps this component isolated from
    ``master_lookup.py``. Objects must expose ``consistent`` and ``by_country``
    dictionaries with the project's existing structure.
    """
    mappings: list[ApprovedMapping] = []
    for field_key, lookup in lookups.items():
        consistent = getattr(lookup, "consistent", {})
        by_country = getattr(lookup, "by_country", {})
        for source_value, label in consistent.items():
            mappings.append(ApprovedMapping(field_key, source_value, label))
        for country, country_mappings in by_country.items():
            for source_value, label in country_mappings.items():
                mappings.append(
                    ApprovedMapping(field_key, source_value, label, country)
                )
    return mappings


def _collapse(value: str | None) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _identity_key(value: str | None) -> str:
    return _collapse(value).casefold()


def _lexical_key(value: str | None) -> str:
    if value is None:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return " ".join(re.sub(r"[^\w]+", " ", without_marks).split())


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    padded = f" {text} "
    if len(padded) <= n:
        return {padded}
    return {padded[index : index + n] for index in range(len(padded) - n + 1)}


def _lexical_score(left: str, right: str) -> float:
    """Match the existing spelling/token/character lexical strategy."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    sequence = SequenceMatcher(None, left, right).ratio()
    left_tokens, right_tokens = set(left.split()), set(right.split())
    token_union = left_tokens | right_tokens
    token_score = (
        len(left_tokens & right_tokens) / len(token_union) if token_union else 0.0
    )
    left_grams, right_grams = _char_ngrams(left), _char_ngrams(right)
    gram_score = (
        2 * len(left_grams & right_grams) / (len(left_grams) + len(right_grams))
        if left_grams or right_grams
        else 0.0
    )
    return max(sequence, token_score, gram_score)


def _bounded_cosine(left: Vector, right: Vector) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding vectors have inconsistent dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    cosine = sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
    return min(1.0, max(0.0, cosine))


def _rank_key(item: RankedEvidence) -> tuple:
    return (
        -item.score,
        -item.semantic_score,
        -item.lexical_score,
        item.label.casefold(),
        item.source_value.casefold(),
        item.country.casefold(),
    )
