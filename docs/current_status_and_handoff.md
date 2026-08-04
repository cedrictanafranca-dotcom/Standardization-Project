# Standardization Project — Current Status and Handoff

Last updated: 2026-08-04

## 2026-08-04 reviewed-validation update

- A 150-record blinded sample was independently mapped and compared with the
  existing pipeline.
- The user decided all 24 disagreement cases and confirmed a risk-balanced
  20-record spot-check drawn from the 126 agreement cases.
- The review confirmed 18 existing-tool corrections and six prompt-policy
  clarifications. All 20 agreement spot-checks were confirmed.
- The provisional full-sample result is 132/150 (88.0%) only if the remaining
  106 unreviewed agreement cases are assumed correct. It is not a final
  production accuracy claim.
- The 24 user-decided disagreement mappings now live in
  `data/reviewed_overrides.json`. They have highest exact-lookup priority but
  are deliberately excluded from similarity candidates and automation-policy
  calibration.
- The Positions, Business Legal Form, PSC/Beneficiary Type, and BRN prompts
  were updated with the user's six policy decisions and the generalizable
  reviewed rules.
- Four focused override/prompt regression tests pass. The pre-existing offline
  routing, alias, LLM-contract, predictive, semantic, evaluation, analytics,
  and correction tests also pass. No live API call was made.
- Next: run the corrected pipeline against the reviewed sample as a regression
  check, then create and review a fresh unseen 50–100-record validation sample.

## 2026-08-04 fresh live validation run

- Source: `C:\Users\cedric.tanafranca\Downloads\No candidate found-data-2026-08-04 10_13_40.csv`
- The user approved sending unresolved classification values to the configured
  Anthropic API for this run.
- 387 of 387 rows were processed; all field types and all 41 country IDs were
  recognized.
- Output has zero blank standardized values, zero non-canonical values, zero
  conflicting duplicate decisions, and zero failed API batches.
- Five rows were flagged for review.
- Across 262 distinct canonical decisions: 197 used historical exact lookup,
  one used a reviewed override, 58 were classified by Claude, and six BRN
  decisions used the validation-backed similarity policy.
- Classified output: `output/live_validation_2026-08-04/No candidate found-classified-2026-08-04.csv`
- Pending user review: `output/live_validation_2026-08-04/fresh_validation_review_100.md`
- The review set contains all 64 fresh decisions plus 36 deterministic exact
  spot checks. Once completed, compare the user's final decisions with
  `fresh_validation_review_100_manifest.json`.

### Fresh review completed

- The user completed all 100 final decisions and accepted 99 tool mappings.
- All 58 Claude API decisions and all six validated-similarity decisions were
  confirmed, as were all five mandatory-review rows.
- The only correction was Taiwan `General Manager`: historical lookup returned
  `Executive Management`; the user selected `Other / Unclassified`.
- That decision is now a country-specific reviewed override and is covered by
  regression tests.
- The result is 99.0% user-reviewed prompt compliance on this sample, exceeding
  the 90% pilot target. This is not an independent subject-matter-expert
  accuracy claim.
- Detailed results: `output/live_validation_2026-08-04/fresh_validation_results_summary.md`.

## Where to resume

- Project folder: `C:\Users\cedric.tanafranca\Desktop\Standardization Project`
- Working branch: `codex/predictive-integration`
- Latest implementation commit before this handoff: `5fd71de` (`Calibrate high-precision automation policy`)
- The integration branch has not been merged into `main` or pushed to a remote.
- `peek_analytics.py` is an unrelated untracked file and must be preserved.

## What is complete

Four previously separate workstreams were integrated:

1. Golden dataset and offline evaluation tooling.
2. Safe lexical aliases and modifier safeguards.
3. Similarity and optional semantic retrieval evidence.
4. Stricter Claude classification, canonical-output validation, and optional verification.

The integrated pipeline now follows this order:

1. Resolve exact approved historical mappings locally.
2. Apply only aliases approved by the measured automation policy.
3. Automatically accept similarity results only for routes that passed validation.
4. Give unresolved values and relevant approved examples to Claude.
5. Require Claude to return a valid canonical taxonomy value.
6. Send uncertain or ambiguous results to the review queue.

The automation policy is bound to the current master lookup file. If that lookup changes, the policy must be recalibrated before its automatic rules can be used again.

## Offline validation completed

- 72 formal offline tests passed after automation calibration.
- The leakage-free validation sample produced 26 automatic decisions, all 26 correct.
- This was 100% measured precision on a small validation sample, so it is encouraging but not sufficient by itself to prove production-wide accuracy.
- The validated automatic similarity route is currently narrow: mainly `brn_type`.
- Some position and legal-form routes remain conservative because their measured precision was below the 92% policy target or their sample was too small.

Important tracked references:

- `docs/integrated_predictive_pipeline.md`
- `docs/automation_calibration_report.md`
- `data/automation_policy.json`

## Live production-style test completed

Source file used locally:

`C:\Users\cedric.tanafranca\Downloads\No translation match found-data-2026-07-28 14_46_29.csv`

The user explicitly approved sending this test file's classification data to the configured Anthropic API and approved the API cost.

Test characteristics:

- 8,933 total CSV rows.
- 8,932 usable data rows plus one footer/blank-core row.
- 84 country IDs, all resolved.
- Nine incoming field-type labels, all recognized and normalized into five canonical field groups.

Live results:

- 8,932 of 8,932 usable rows received a standardized value.
- 7,324 rows (82.0%) completed without human review.
- 1,608 rows (18.0%) were flagged for human review.
- Zero failed rows or failed API batches.
- Zero blank standardized values on usable rows.
- Zero standardized values outside their configured canonical taxonomies.

Review volume after canonical field-name normalization:

| Canonical field | Rows | No review | Needs review |
| --- | ---: | ---: | ---: |
| Universal Position | 5,878 | 4,688 | 1,190 |
| Universal Business Legal Form | 2,378 | 1,997 | 381 |
| Universal Business Status | 462 | 430 | 32 |
| Universal Beneficiary Type | 139 | 134 | 5 |
| BRN Type | 75 | 75 | 0 |
| **Total** | **8,932** | **7,324** | **1,608** |

Combined classified output, stored locally and intentionally excluded from Git:

`output\test_run_2026-07-30\No translation match found-classified-2026-07-30.csv`

Nine field-level checkpoint CSV files are stored in the same directory.

## What the live test proves—and does not prove

It proves that the full upload-shaped data can be routed, classified, recombined, and validated without missing or invalid outputs. It also shows that 82% of these rows would not require human intervention under the current review rules.

It does not prove 90% classification accuracy because the source file contains occurrence volumes rather than verified correct standardized answers. Accuracy requires comparison with human-approved expected answers or a manually reviewed representative sample.

## Known limitations

1. Similarity retrieval is too slow for unusually large files containing thousands of unfamiliar values. The 8,932-row test took much longer than desired, especially for country-dependent position fields. Expected operational files are at most about 250 rows, so this is not currently a blocking problem, but it should be optimized before routinely processing large exports.
2. The current process writes a completed field result only after the whole field finishes. Batch-level checkpoints would make long runs more resilient.
3. The production semantic-embedding provider is not configured. The included deterministic embedding provider is for offline testing, not production semantics.
4. The observed 18% review rate may be higher than the desired long-term level, particularly for positions and legal forms.
5. The integration branch still needs final review before merging into `main`.

## Recommended next steps

1. Draw a representative sample of approximately 100–200 rows from the 7,324 no-review results, including every field group and a mix of lookup-, similarity-, and Claude-generated decisions.
2. Have a knowledgeable reviewer record the correct standardized value for that sample.
3. Measure actual precision. If it is at least 90%, use the result as the initial production acceptance baseline. If it is below 90%, use the errors to tighten prompts, aliases, and field-specific automation policy.
4. Test a normal operational file of no more than 250 rows through the web app and confirm the user workflow, download, and review process.
5. Optimize similarity retrieval with indexing/caching and add batch-level checkpoints when large-file performance becomes a priority.
6. Re-run the combined automated test suite, review the branch diff, then merge `codex/predictive-integration` into `main` when approved.

## Mapping-reason feature completed (2026-08-04)

- Every output row now includes a nonblank `Mapping Reason`.
- Reasons combine a taxonomy-based explanation with decision provenance; they
  never cite historical mapping as the sole basis.
- Reviewed overrides, historical lookups, approved aliases, similarity
  decisions, model decisions, placeholders, blanks, unknown fields, and API
  failures each receive route-appropriate wording.
- The flagged-review UI displays `Mapping Reason` beside the override dropdown.
- Confirming or changing a flagged value replaces the explanation with the
  final reviewed-selection rationale before export.
- The implementation adds no per-row explanation API calls.
- Focused mapping/review tests and the broader offline routing suites passed.

## Security and portability notes

- `.env` contains local configuration and must remain excluded from Git.
- `output/` contains generated results and test data and must remain excluded from Git.
- Do not commit the source test CSV or classified output unless it has been explicitly approved and appropriately sanitized.
- The committed code and this handoff document remain available when switching Codex accounts on the same computer.
- Because the branch has not been pushed, moving to another computer requires a secure repository push or a separate project-folder backup.
