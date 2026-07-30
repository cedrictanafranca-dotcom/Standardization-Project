# Lexical Alias and Safeguard Component

`src/lexical_aliases.py` provides conservative, deterministic lexical
classification evidence. It is intentionally isolated from the application
and standardization pipeline so it can be reviewed and tested before
integration.

## Public interface

```python
from lexical_aliases import MatchOutcome, load_default_matcher

matcher = load_default_matcher()
result = matcher.match(
    field_key="positions_designations",
    raw_value="C.E.O.",
    country="United Kingdom",
)

if result.safe_to_accept:
    canonical_value = result.canonical_value
elif result.outcome is MatchOutcome.REVIEW:
    # Pass the original value, result.suggested_value, result.evidence, and
    # result.warnings to the classifier or a human review step.
    ...
else:
    # Continue through the normal classification path.
    ...
```

The public entry points are:

- `load_default_matcher()` loads and validates
  `data/lexical_aliases.json`.
- `LexicalAliasMatcher.from_file(path)` loads another rule set.
- `LexicalAliasMatcher.from_dict(payload)` supports tests and validation tools.
- `LexicalAliasMatcher.match(field_key, raw_value, country="")` returns a
  `LexicalResult`.
- `normalize_lexical(value)` exposes the harmless normalization used by the
  matcher.

`LexicalResult.canonical_value` is populated only when `safe_to_accept` is
true. A review result may carry `suggested_value`, but that value is evidence
about the unmodified base alias and must never be treated as an automatic
classification.

## Safety model

The matcher performs exact lookup after:

- Unicode case folding;
- accent removal;
- punctuation and repeated-whitespace normalization; and
- joining dotted abbreviation letters, such as `C.E.O.` to `ceo`.

It does not perform edit-distance matching, stemming, substring alias
matching, semantic matching, or token reordering. A typo such as `CFOO` is
therefore a no-match rather than an uncertain fuzzy acceptance.

Meaning-changing terms are configured per field. For example, removing
`assistant` from `assistant director` exposes the approved base alias
`director`, but the result is `REVIEW` with `Director` only as a suggestion.
The component does not force that classification.

A complete phrase containing a modifier can be accepted only when:

1. the complete phrase is an explicit alias; and
2. its `covers_modifiers` list names every detected modifier.

This is how the reviewed phrases `non-executive director`, `foreign company`,
`branch`, and `non-profit` remain safe while unreviewed combinations such as
`deputy director`, `foreign LLC`, and `branch company` are held for review.

Country-specific aliases override a global alias for the same normalized
phrase. The default configuration applies the positions prompt's special
CEO/Managing Director rule for the United Kingdom, Gibraltar, Ireland, and
Malta. Other-country mappings are never borrowed.

## Rule-file maintenance

`data/lexical_aliases.json` is the reviewable source of truth. Each field owns:

- its allowed canonical values;
- exact aliases and abbreviation expansions;
- optional country scopes;
- optional modifier phrases and warnings; and
- explicit modifier coverage for reviewed full-phrase aliases.

Configuration loading fails with `RuleConflictError` for:

- the same normalized alias mapping to different values in one scope;
- duplicate aliases in one scope;
- conflicting or duplicate modifier rules;
- aliases targeting a non-canonical value;
- abbreviations without expansions;
- invalid rule kinds; or
- aliases claiming to cover an undeclared or absent modifier.

Global aliases and country-specific overrides are deliberately allowed because
their scopes do not conflict.

## Recommended later integration

The integration branch should call this component after the exact master
lookup and local artifact/data-quality filters, but before fuzzy prediction or
an API call:

1. `MATCH`: use `canonical_value`, retain all evidence, and record an
   alias-specific decision count.
2. `REVIEW`: do not use `suggested_value` automatically. Supply its evidence
   and warnings to the normal classifier or review workflow.
3. `NO_MATCH`: continue unchanged through the existing predictive/API path.

Record the rule-file version with each run. Regression reporting should
separate exact lookup, approved alias, fuzzy prediction, retrieval-assisted
API, and ordinary API decisions. Incorrect automatic alias matches should be
tracked as a dedicated high-risk metric.
