# Integrated accuracy-first classification pipeline

The four predictive workstreams are integrated on
`codex/predictive-integration`. The production pipeline in
`src/standardize_file.py` now uses the following order for each unique value:

1. Exact approved master-lookup match.
2. System-artifact and data-quality filters.
3. Exact, field-specific approved alias match.
4. Modifier safeguard evaluation.
5. Approved lexical and optional semantic evidence retrieval.
6. Strict canonical classifier call.
7. Optional independent verification.
8. Human review for modifier cases, conflicting semantic neighbors,
   classifier/verifier disagreement, invalid output, or low confidence.

## Automatic decisions

Only these routes are automatic by default:

- exact approved lookup matches;
- deterministic data-quality filters; and
- complete aliases explicitly approved in `data/lexical_aliases.json`.

Legacy near-identical similarity prediction is disabled by default. It can be
enabled explicitly with `allow_similarity_predictions=True` or the CLI flag
`--allow-similarity-predictions`, but should remain disabled until the golden
evaluation demonstrates an acceptable incorrect-HIGH rate.

Semantic results are evidence only. The highest-scoring semantic neighbor is
never copied directly into the output. Nearby competing labels force human
review even if the classifier returns HIGH confidence.

## Embedding configuration

The application does not select, install, download, or contact an embedding
provider. An approved adapter implementing `EmbeddingProvider` must be injected:

```python
from standardize_file import configure_embedding_provider

configure_embedding_provider(approved_provider)
```

`src/embedding_providers.py` contains a dependency-free
`DeterministicHashEmbeddingProvider`. It exists only to test the integration
offline. It is not a semantic model and must not be used to claim production,
multilingual, or accuracy improvements. The CLI flag `--offline-semantic`
enables this test double for a local dry run.

Before choosing a real provider, confirm data-handling approval, hosting,
retention, residency, credentials, model revision, cache invalidation, and
measured accuracy on the leakage-free golden dataset.

## Optional verification

`standardize_dataframe()` accepts a `VerificationPolicy` and optional separate
verification client. The CLI flag `--verify-uncertain` uses the current client
for an independent second pass. A disagreement or malformed verification is
routed to human review instead of silently choosing one answer.

Verification is not enabled by default because it can add calls and cost. It
should be enabled for a controlled golden-dataset comparison before being made
the application default.

## Offline verification

Run the combined routing suite:

```powershell
.venv\Scripts\python.exe test_integrated_routing.py
```

Run the component and regression suites:

```powershell
.venv\Scripts\python.exe test_lexical_aliases.py
.venv\Scripts\python.exe test_semantic_retrieval.py
.venv\Scripts\python.exe test_llm_accuracy.py
.venv\Scripts\python.exe test_predictive_lookup.py
.venv\Scripts\python.exe src\test_contract.py
$env:PYTHONPATH = (Get-Location).Path
.venv\Scripts\python.exe tests\evaluation\test_evaluation.py
```

No test or default application path makes an embedding-network call. Live
Claude evaluation remains separately gated and requires explicit approval.

## Next accuracy decision

Use `evaluation/README.md` to compare prompt-only, alias-assisted,
retrieval-assisted, and opt-in predictive approaches. Do not enable a live
embedding provider or automatic similarity predictions based only on component
tests; require measured improvement and an acceptable incorrect-HIGH rate.
