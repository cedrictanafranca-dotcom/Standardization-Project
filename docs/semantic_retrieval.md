# Semantic retrieval component

`src/semantic_retrieval.py` is an isolated evidence retriever for approved
standardization mappings. It does not classify values, set confidence, or
write to the master lookup. Its output is intended for Claude and the future
decision engine.

## Retrieval contract

`SemanticRetriever.retrieve()` requires a query, field key, and optional
country. It returns:

- Up to four ranked approved mappings by default.
- The source value, canonical label, country, field, semantic score, lexical
  score, and combined score for each mapping.
- Competing labels whose best evidence is within the configured score window
  of the top result.

Candidates are always restricted to the requested field. Global mappings are
eligible for every country; mappings for the requested country override an
identical global source value. Mappings belonging to other countries are
excluded. With no country context, only global mappings are used.

The combined score is a weighted semantic/lexical score with a lexical floor:
`max(lexical, 0.70 * semantic + 0.30 * lexical)`. The floor preserves the
existing behavior for near-identical spelling variants if an embedding model
produces a surprising vector. This score is evidence strength, not
classification confidence.

## Provider and cache interface

Embedding providers implement two members:

```python
class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...
```

The component batches missing texts and caches vectors under `model_id` plus
normalized text. An application can inject a normal dictionary for in-process
caching or a persistent mutable mapping adapter. Changing `model_id` prevents
vectors from different models from being mixed.

No embedding library, model, or API client is a required dependency. The unit
tests use a deterministic fake provider and make no network calls.

## Integration with the current lookup

The existing `FieldLookup` objects can be adapted without modifying their
implementation:

```python
from master_lookup import load_lookup
from semantic_retrieval import (
    SemanticRetriever,
    approved_mappings_from_lookups,
)

lookups = load_lookup()
mappings = approved_mappings_from_lookups(lookups)
retriever = SemanticRetriever(mappings, embedding_provider)

result = retriever.retrieve(
    "upravlyayushchiy direktor",
    field_key="positions_designations",
    country="United Kingdom",
)
```

For pipeline integration, preserve the current order:

1. Exact lookup.
2. Artifact and data-quality filters.
3. Existing conservative lexical prediction, if it remains enabled.
4. Hybrid semantic retrieval for unresolved values.
5. Claude or the future decision engine makes the classification.

Pass only `result.evidence` plus `result.conflicts` as context. Do not turn the
top evidence item into an automatic mapping. Prompt formatting should identify
country and both component scores, and should explicitly call out conflicting
labels. The integration branch now performs this wiring. Semantic results
remain evidence-only, conflicts are presented explicitly, and competing nearby
labels force review. No real embedding provider is selected or enabled by
default.

## Model dependency and hosting considerations

Measure ranking quality on the golden dataset before selecting a provider or
adding a dependency.

- A local multilingual model avoids sending source values to a third party but
  adds image size, memory, cold-start time, model-license review, and patching
  obligations. Package model weights into a versioned deployment artifact;
  production instances should not download weights at startup.
- A hosted embedding API reduces container size but introduces data-governance,
  availability, latency, cost, credential, and regional-processing concerns.
  Use an approved private endpoint and secret store, and document retention
  behavior before enabling it.
- ECS/EC2 sizing must be benchmarked with the chosen model. CPU-only inference
  may be adequate at the current lookup scale, but concurrency and cold starts
  should be measured. GPU hosting should be justified by measured throughput.
- Persist candidate embeddings keyed by model ID and lookup version. Rebuild
  the index when the model or approved lookup changes. Query vectors may use a
  bounded in-memory cache.
- Keep the embedding package optional until semantic ranking shows a material
  accuracy lift over the lexical baseline. Pin the provider and model revision
  once approved.

## Verification

Run the deterministic suite without installing any packages:

```powershell
py -m unittest test_semantic_retrieval.py
```

The suite covers multilingual and transliterated ranking, lexical/semantic
combination, field and country isolation, conflict surfacing, bounded evidence,
embedding caching, and a 4,000-candidate runtime check.
