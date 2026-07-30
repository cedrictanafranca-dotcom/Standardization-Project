# Offline automation calibration report

Date: 2026-07-30  
Target automatic-mapping precision: 92%  
Source: 4,846 approved mappings, with a leakage-free 969-record holdout

## Result

The held-out families were divided into 635 calibration records and 334
validation records with zero family overlap. Similarity thresholds were chosen
on calibration and enabled only after independently meeting the target on
validation.

On the validation partition, the enabled deterministic policy produced:

- 26 automatic decisions;
- 26 correct decisions;
- 100% measured precision; and
- 7.8% coverage of deliberately unseen values.

This does **not** mean the application automates only 7.8% of normal work.
Exact saved mappings, duplicate reuse, blanks, and data-quality filters are
intentionally absent or underrepresented in a family-held-out test. Those
routes still avoid API and human work in normal files.

## Routes enabled

- **BRN Type similarity:** enabled at score >= 0.55 and neighbor agreement >=
  0.67. It achieved 98.6% on 74 calibration decisions and 100% on 25 validation
  decisions, covering 75.8% of unseen validation BRN values.
- **Business Legal Form approved aliases:** enabled. The fixed alias route was
  correct on all three held-out alias cases. This is a small sample and remains
  separately visible in run statistics.

## Routes not enabled

- Positions / Designations aliases achieved 87.5% (49/56), below target.
- Business Legal Form text similarity achieved 85.7% on validation.
- Positions / Designations similarity achieved 56.7% on validation.
- Other fields lacked enough held-out deterministic-route examples.

Disabled aliases are still passed to Claude as evidence. They are not discarded
and do not automatically require human review. Disabled similarity results also
remain retrieval evidence.

## Ambiguity analysis

The apparent 401 ambiguous records collapse to only 26 value families:

- 249 records in near-variant label-disagreement families;
- 82 records around an `Other / Unclassified` boundary; and
- 70 records explained heuristically by country/context overrides.

The highest-value review list contains 14 near-variant families. The largest
are:

1. CEO / Chief Executive Officer variants — 63 records across Board Member,
   Director, and Executive Management.
2. Director spelling/country variants — 39 records across Board Member,
   Director, and Executive Management.
3. Limited Liability Company variants — 36 records split between Company and
   Foreign Entity / Branch.
4. Tax Registration Number variants — 30 records split between Business
   Registration Number and Tax ID Number.
5. Profit / nonprofit / foreign corporation variants — 24 records across
   Company, Foreign Entity / Branch, and Non-Profit / Cooperative.
6. Domestic profit / nonprofit corporation variants — 17 records split between
   Company and Non-Profit / Cooperative.
7. Generic registration-number variants — 11 records split between Business
   Registration Number and Charity Number.

The remaining high-priority families are smaller combinations involving
domestic profit status, good standing, registered/deregistered, mixed legal
representative titles, resident administrators, administrator/director, and
revocation-duration status.

These groupings are review priorities, not claims that the approved mappings
are wrong. Country-specific answers and compound values may legitimately differ.
The complete machine-readable report is generated as
`output/evaluation/ambiguity_report.json`.

## What is needed for minimal human intervention

Text similarity alone cannot safely automate most unseen fields at 92%.
The next coverage increase must be measured with:

1. Claude prompt-only classification;
2. retrieval-assisted Claude classification;
3. optional classifier/verifier agreement; and
4. an approved real semantic embedding provider.

Those routes require a separately approved live evaluation. The offline policy
does not estimate or claim their accuracy.
