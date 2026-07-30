# Golden-dataset evaluation

This package builds a deterministic holdout from `data/master_lookup.json`,
which is treated as the authoritative approved-answer source. It never edits
that file.

## Leakage controls

- Values are grouped within each field using case/accent/punctuation
  normalization plus token, edit, and character-ngram similarity.
- Connected value families are assigned wholly to reference or test.
- Country variants of a value share the same family, so country-specific
  answers cannot leak through the global or another-country lookup.
- The generated `reference_lookup.json` contains only reference families.
- Dataset creation fails if any family overlaps reference and test.
- The manifest records the source SHA-256, seed, family threshold, coverage,
  and a zero-overlap assertion.

The production JSON is a flattened approved lookup and does not retain source
row occurrence counts. Therefore the evaluation's documented frequency proxy
is: `common` means a family has two or more approved mapping records (variants
and/or countries); `rare` means a singleton. For true traffic-weighted
common/rare metrics, join production occurrence counts by
`(field, country, raw_value)` before splitting.

## Build the holdout

Run from the repository root:

```powershell
python -m evaluation.cli build `
  --lookup data\master_lookup.json `
  --output-dir output\evaluation `
  --seed 20260729 `
  --test-fraction 0.20
```

Outputs:

- `heldout.jsonl` — test records and authoritative expected answers
- `reference_lookup.json` — leakage-free retrieval/predictive reference
- `manifest.json` — provenance, parameters, and balance diagnostics

Changing the seed creates a repeatable alternate holdout. Keep the threshold
fixed when comparing approaches.

## Prediction contract and metrics

Every approach writes one JSON object per held-out record:

```json
{"record_id":"...","predicted_value":"Company","confidence":"HIGH","needs_review":false,"route":"predictive","api_bound":false}
```

`route` should identify `prompt-only`, `retrieval-assisted`, `predictive`, or
another future approach. `api_bound` indicates that the value required an API
call. Score any approach with:

```powershell
python -m evaluation.cli score `
  --dataset output\evaluation\heldout.jsonl `
  --predictions output\evaluation\prompt-only.jsonl `
  --approach prompt-only `
  --output output\evaluation\prompt-only-report.json
```

The report includes overall accuracy; accuracy by field, canonical category,
country, frequency band, and ambiguity; incorrect HIGH classifications;
catch-all rate; review rate; predictive coverage; and API-bound values.

Compare prompt-only, retrieval-assisted, and predictive reports:

```powershell
python -m evaluation.cli compare `
  output\evaluation\prompt-only-report.json `
  output\evaluation\retrieval-report.json `
  output\evaluation\predictive-report.json `
  --output output\evaluation\comparison.json
```

## Optional live API evaluation

Do not run this without explicit cost approval. The runner has two gates and
will refuse to call the API unless both are present:

```powershell
python -m evaluation.live_api `
  --dataset output\evaluation\heldout.jsonl `
  --reference output\evaluation\reference_lookup.json `
  --approach retrieval-assisted `
  --output output\evaluation\retrieval.jsonl `
  --live `
  --cost-approval I_APPROVE_LIVE_API_COST
```

Use `--approach prompt-only` for the no-retrieval baseline. The runner imports
the existing prompt and parser contracts but does not update the master
lookup. No live calls are made by dataset generation, scoring, comparison, or
tests.

## Tests

```powershell
python -m unittest discover -s tests\evaluation -v
```
