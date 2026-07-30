"""Offline embedding adapters used to wire and test semantic retrieval.

No provider in this module makes a network call.  The deterministic hash
provider is a development/test double, not an approved production model.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence


class DeterministicHashEmbeddingProvider:
    """Stable, dependency-free fake embeddings for offline integration tests.

    The vectors are derived from normalized word and character features so
    related spellings have some signal, but they are not semantic embeddings
    and must not be used to claim multilingual or production accuracy.
    """

    model_id = "offline-deterministic-hash-v1-not-for-production"

    def __init__(self, dimensions: int = 96) -> None:
        if dimensions < 16:
            raise ValueError("dimensions must be at least 16")
        self.dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        return [self._embed_one(str(text)) for text in texts]

    def _embed_one(self, text: str) -> tuple[float, ...]:
        normalized = _normalize(text)
        features = normalized.split()
        compact = normalized.replace(" ", "")
        features.extend(
            f"#3:{compact[index:index + 3]}"
            for index in range(max(len(compact) - 2, 0))
        )
        vector = [0.0] * self.dimensions
        for feature in features or ["[empty]"]:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return tuple(value / norm for value in vector)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return " ".join(re.sub(r"[^\w]+", " ", without_marks).split())
