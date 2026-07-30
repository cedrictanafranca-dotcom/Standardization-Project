"""Normalized value-family construction.

Families are deliberately label-blind: only raw text is used. Connected
components are used instead of independent random rows so that if A is close
to B, and B is close to C, all three remain on one side of the split.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Iterable

from .models import EvaluationRecord

DEFAULT_FAMILY_THRESHOLD = 0.88


def normalize_value(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    without_marks = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(re.sub(r"[^\w]+", " ", without_marks).split())


def _char_ngrams(value: str, n: int = 3) -> set[str]:
    compact = value.replace(" ", "")
    padded = f" {compact} "
    if len(padded) <= n:
        return {padded}
    return {padded[index:index + n] for index in range(len(padded) - n + 1)}


def similarity(left: str, right: str) -> float:
    left_n, right_n = normalize_value(left), normalize_value(right)
    if not left_n or not right_n:
        return 0.0
    if left_n == right_n:
        return 1.0
    sequence = SequenceMatcher(None, left_n, right_n).ratio()
    left_tokens, right_tokens = set(left_n.split()), set(right_n.split())
    union = left_tokens | right_tokens
    token_score = len(left_tokens & right_tokens) / len(union) if union else 0.0
    left_grams, right_grams = _char_ngrams(left_n), _char_ngrams(right_n)
    gram_score = (
        2 * len(left_grams & right_grams) / (len(left_grams) + len(right_grams))
        if left_grams or right_grams else 0.0
    )
    return max(sequence, token_score, gram_score)


class _UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        winner, loser = sorted((left_root, right_root))
        self.parent[loser] = winner


def build_family_map(
    records: Iterable[EvaluationRecord],
    threshold: float = DEFAULT_FAMILY_THRESHOLD,
) -> dict[tuple[str, str], str]:
    """Return {(field, raw_value): stable_family_id}.

    Candidate generation uses shared character trigrams, plus exact normalized
    keys. It is much cheaper than an all-pairs comparison while still finding
    case, punctuation, accent, spacing, and small spelling variants.
    """
    if not 0.0 < threshold <= 1.0:
        raise ValueError("family threshold must be in (0, 1]")

    raw_by_field: dict[str, set[str]] = defaultdict(set)
    for record in records:
        raw_by_field[record.field].add(record.raw_value)

    result: dict[tuple[str, str], str] = {}
    for field, raw_values_set in sorted(raw_by_field.items()):
        raw_values = sorted(raw_values_set, key=lambda item: (normalize_value(item), item))
        union_find = _UnionFind(raw_values)
        by_normalized: dict[str, list[str]] = defaultdict(list)
        by_gram: dict[str, list[str]] = defaultdict(list)

        for raw in raw_values:
            normalized = normalize_value(raw)
            by_normalized[normalized].append(raw)
            for gram in _char_ngrams(normalized):
                by_gram[gram].append(raw)

        candidate_pairs: set[tuple[str, str]] = set()
        for bucket in list(by_normalized.values()) + list(by_gram.values()):
            ordered = sorted(set(bucket))
            for left_index, left in enumerate(ordered):
                for right in ordered[left_index + 1:]:
                    candidate_pairs.add((left, right))

        for left, right in sorted(candidate_pairs):
            left_n, right_n = normalize_value(left), normalize_value(right)
            max_length = max(len(left_n), len(right_n), 1)
            if abs(len(left_n) - len(right_n)) / max_length > 0.35:
                continue
            if similarity(left, right) >= threshold:
                union_find.union(left, right)

        members: dict[str, list[str]] = defaultdict(list)
        for raw in raw_values:
            members[union_find.find(raw)].append(raw)
        for component in sorted(members.values(), key=lambda values: values[0]):
            identity = field + "\0" + "\0".join(sorted(normalize_value(v) for v in component))
            family_id = f"{field}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
            for raw in component:
                result[(field, raw)] = family_id
    return result
