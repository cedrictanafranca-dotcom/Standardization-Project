r"""Step 3 — Handle real file structure. Step 4 — batching, retry, logging.
Step 5 — multi-field support.

Takes a real-shaped input file and returns the SAME file with one column added,
without disturbing anything else:

  3.1  detect the raw-value column flexibly (--column, else auto-detect by a
       list of common header names).
  3.2  every other column passes through untouched.
  3.3  a "Standardized Value" column is inserted right next to the raw column.
  3.4  edge cases:
         - blank / whitespace-only raw values are filled locally (no API call),
         - duplicate raw values are classified ONCE and reused,
         - the unique values are chunked into batches so a big file never
           becomes one oversized API call.
  4.1  batch size is controllable (--batch-size) so batches fit the model's
       context window.
  4.2  each batch's API call goes through retry-with-backoff (src/retry.py)
       for transient errors (rate limits, timeouts, 5xx); a batch that
       exhausts its retries is marked distinctly rather than crashing the run.
  4.3  a run log entry (input/output counts, retries, mismatches, failures)
       is appended to output/run_log.jsonl and summarized on screen.
  5.1  each field's instructions live in their own file under /prompts.
  5.2  --field looks the field up in the registry (src/fields.py): field name
       -> prompt file -> expected standard values. Adding a field means adding
       one entry there — no changes needed here.
  5.3  the prompt loaded, and the catch-all value used for blanks, both come
       from whichever --field was selected instead of being hardcoded.
  8.1  the output contract now includes a confidence level (HIGH/MEDIUM/LOW)
       per value (src/classifier.py CONFIDENCE_ADDENDUM), appended to the
       field's prompt at load time.
  8.2  LOW-confidence, missing-confidence, and permanently-failed rows are
       surfaced in a "Needs Review" column instead of a separate review UI.

Still uses the simulated client by default (no API key). --live swaps in the
real Anthropic call; the file-handling logic here is identical either way.
--simulate-flaky / --simulate-broken inject REAL anthropic error types (no
live API needed) to prove the retry/logging actually work before real money
is spent.

Run:
    .venv\Scripts\python.exe src\standardize_file.py                                 # mock, Positions, sample file
    .venv\Scripts\python.exe src\standardize_file.py --field business_legal_form --data data\sample_blf.xlsx
    .venv\Scripts\python.exe src\standardize_file.py --data data\yourfile.xlsx
    .venv\Scripts\python.exe src\standardize_file.py --batch-size 5        # show chunking
    .venv\Scripts\python.exe src\standardize_file.py --simulate-flaky 2    # show retry recovery
    .venv\Scripts\python.exe src\standardize_file.py --simulate-broken     # show a batch giving up
    .venv\Scripts\python.exe src\standardize_file.py --live                # real API
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

import pandas as pd

import config
import fields
import run_log
from classifier import (
    CONFIDENCE_ADDENDUM,
    DECISION_HUMAN_REVIEW,
    DECISION_VERIFIED,
    ClassificationRequest,
    MockClaudeClient,
    RealClaudeClient,
    VerificationPolicy,
    classify_request,
    classify_values,
)
from fault_injection import FlakyClient, rate_limit_error, server_error
from jira_ticket import build_ticket_text, find_countries
from mapping_reason import build_mapping_reason
from master_lookup import load_lookup
from retry import RetryExhaustedError, call_with_retry
from lexical_aliases import LexicalAliasMatcher, MatchOutcome, load_default_matcher
from semantic_retrieval import (
    EmbeddingProvider,
    SemanticRetriever,
    approved_mappings_from_lookups,
)
from embedding_providers import DeterministicHashEmbeddingProvider
from automation_policy import (
    AutomationPolicy,
    load_automation_policy,
    summarize_similarity_matches,
)

# Load the master lookup once at module import time.  Returns an empty dict
# gracefully if data/master_lookup.json doesn't exist yet — the pipeline
# continues without it and sends everything to the API.
_MASTER_LOOKUP = load_lookup()
_ALIAS_MATCHER = load_default_matcher()
_EMBEDDING_PROVIDER: EmbeddingProvider | None = None
_SEMANTIC_RETRIEVER: SemanticRetriever | None = None
_AUTOMATION_POLICY_FILE = config.DATA_DIR / "automation_policy.json"
_USE_CONFIGURED_POLICY = object()


def _load_configured_automation_policy() -> AutomationPolicy | None:
    if not _AUTOMATION_POLICY_FILE.exists():
        return None
    policy = load_automation_policy(_AUTOMATION_POLICY_FILE)
    lookup_path = config.DATA_DIR / "master_lookup.json"
    if lookup_path.exists() and policy.source_lookup_sha256:
        actual_hash = hashlib.sha256(lookup_path.read_bytes()).hexdigest()
        if actual_hash != policy.source_lookup_sha256:
            return None
    return policy


_AUTOMATION_POLICY = _load_configured_automation_policy()


def configure_embedding_provider(
    provider: EmbeddingProvider | None,
) -> SemanticRetriever | None:
    """Configure semantic evidence retrieval without selecting a vendor here.

    Passing ``None`` disables semantic retrieval.  Provider adapters own all
    model, hosting, credential, and network behavior; the standardization
    pipeline never downloads a model or chooses an external service.
    """
    global _EMBEDDING_PROVIDER, _SEMANTIC_RETRIEVER
    _EMBEDDING_PROVIDER = provider
    _SEMANTIC_RETRIEVER = (
        SemanticRetriever(
            approved_mappings_from_lookups(_MASTER_LOOKUP),
            provider,
        )
        if provider is not None
        else None
    )
    return _SEMANTIC_RETRIEVER


def reload_lookup() -> None:
    """Reload the in-process lookup cache from disk (call after updating master_lookup.json)."""
    global _MASTER_LOOKUP, _AUTOMATION_POLICY
    _MASTER_LOOKUP = load_lookup()
    _AUTOMATION_POLICY = _load_configured_automation_policy()
    if _EMBEDDING_PROVIDER is not None:
        configure_embedding_provider(_EMBEDDING_PROVIDER)

STANDARDIZED_COLUMN = "Standardized Value"
MAPPING_REASON_COLUMN = "Mapping Reason"
# Column header AND the flag value written into it when a row is flagged
# (blank otherwise) — a single constant serves both, by design.
NEEDS_REVIEW_COLUMN = "Needs Review"
# Reasoning shown for MEDIUM and LOW rows; blank for HIGH.
REVIEW_REASON_COLUMN = "Review Reason"
DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_RETRY_BASE_DELAY = 1.0
DEFAULT_FIELD = "positions_designations"
# A batch that exhausts its retries gets this instead of silently vanishing.
# (Not a taxonomy value — always this literal, regardless of field.)
ERROR_FILL = "ERROR - Not Classified (API Failure)"

DEFAULT_DATA_FILE = config.DATA_DIR / "sample_positions_full.xlsx"

# Header names we'll accept as "the raw-value column" (compared case- and
# whitespace-insensitively). Section 9 notes the header varies: "Inputs",
# "Value", sometimes with a trailing space.
_VALUE_COLUMN_CANDIDATES = [
    "value", "raw value", "raw_value", "raw", "input", "inputs",
    "raw input", "original value", "original", "raw values",
]
_COUNTRY_COLUMN_CANDIDATES = ["country", "countries"]


@dataclass
class Stats:
    raw_column: str
    total_rows: int
    blanks: int
    unique_values: int
    duplicates_collapsed: int
    batches: int
    batch_size: int
    api_calls_saved: int  # rows that did NOT need an API call (dupes + blanks)
    lookup_hits: int = 0   # unique values resolved from the master lookup (no API call)
    alias_matches: int = 0  # approved aliases resolved safely without an API call
    alias_reviews: int = 0  # modifier/alias cases forced through classifier + review
    alias_deferred: int = 0  # alias matches below policy evidence requirements
    similarity_predictions: int = 0  # conservative fuzzy predictions (no API call)
    retrieval_assisted: int = 0  # API values supplied with approved similar examples
    semantic_retrievals: int = 0  # API values supplied with hybrid semantic evidence
    verified_decisions: int = 0  # decisions confirmed by an optional second pass
    verification_reviews: int = 0  # verification outcomes routed to human review
    flagged_count: int = 0  # rows marked Needs Review (LOW/missing confidence, blanks, failures)
    retries_used: int = 0
    failed_batches: list[run_log.BatchFailure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    new_mappings: dict = field(default_factory=dict)
    # (country, raw_value) -> std_value — HIGH confidence API results not in lookup

    @property
    def ok(self) -> bool:
        return not self.warnings and not self.failed_batches


def _norm_key(value) -> str:
    """Normalize a raw cell to a dedup/lookup key ("" means blank)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return " ".join(str(value).casefold().split())


# Matches system/data artifacts like MASKED_WHOIS_DATA, NULL_VALUE, NO_DATA —
# all-caps snake_case with at least one underscore. These are never real business
# values and should be caught before the model sees them.
_SYSTEM_ARTIFACT_RE = re.compile(r'^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$')

# Known placeholder / no-data strings that are definitively Other / Unclassified
# and should never be sent to the API.
_DATA_QUALITY_PLACEHOLDERS = frozenset({
    "n/a", "na", "n.a.", "n/a.", "null", "none", "unknown", "not available",
    "not applicable", "not specified", "not provided", "not found",
    "-", ".", "/", "?", "—", "--", "...",
    "legal form unknown", "legal form not available", "legal form not specified",
    "information not available", "data not available",
})


def _is_data_quality_placeholder(raw: str) -> bool:
    """Return True if raw is a known placeholder / no-data value."""
    if len(raw) <= 1:
        return True
    return raw.lower() in _DATA_QUALITY_PLACEHOLDERS


def detect_value_column(df: pd.DataFrame, user_specified: str | None = None) -> str:
    """Return the raw-value column: user's choice if given, else auto-detect."""
    if user_specified:
        if user_specified in df.columns:
            return user_specified
        raise ValueError(
            f"Column {user_specified!r} not found. Available: {list(df.columns)}"
        )

    normalized = {}
    for col in df.columns:
        normalized.setdefault(str(col).strip().lower(), col)

    matches = []
    for cand in _VALUE_COLUMN_CANDIDATES:
        if cand in normalized and normalized[cand] not in matches:
            matches.append(normalized[cand])

    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(
            "Could not auto-detect the raw-value column. Pass one with "
            f"--column. Available columns: {list(df.columns)}"
        )
    raise ValueError(
        f"Ambiguous raw-value column — candidates {matches}. "
        "Pick one with --column."
    )


def detect_country_column(df: pd.DataFrame) -> str | None:
    """Return the country column if one exists, else None (not an error —
    country context is optional; only used when the field is country_dependent)."""
    normalized = {str(col).strip().lower(): col for col in df.columns}
    for cand in _COUNTRY_COLUMN_CANDIDATES:
        if cand in normalized:
            return normalized[cand]
    return None


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _needs_review(confidence: str) -> bool:
    """LOW or missing/unparseable confidence needs a human look (8.2)."""
    return confidence in ("", "LOW")


def read_table(path: Path) -> pd.DataFrame:
    """Read an Excel or CSV file into a DataFrame."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(path)
    if suffix in (".csv", ".txt"):
        return pd.read_csv(path)
    raise ValueError(f"Unsupported file type: {suffix} (use .xlsx or .csv)")


def standardize_dataframe(
    df: pd.DataFrame,
    column: str,
    system_prompt: str,
    client,
    batch_size: int = DEFAULT_BATCH_SIZE,
    blank_fill: str = fields.CATCH_ALL,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    country_dependent: bool = False,
    country_column: str | None = None,
    field_key: str | None = None,
    canonical_values: list[str] | None = None,
    alias_matcher: LexicalAliasMatcher | None = _ALIAS_MATCHER,
    semantic_retriever: SemanticRetriever | None = None,
    allow_similarity_predictions: bool = False,
    verification_policy: VerificationPolicy | None = None,
    verification_client=None,
    automation_policy: AutomationPolicy | None | object = _USE_CONFIGURED_POLICY,
) -> tuple[pd.DataFrame, Stats]:
    """Add a standardized-value column next to `column`, everything else intact.

    country_dependent + country_column: when both are set, classification is
    keyed by (country, raw value) instead of raw value alone, and the model is
    told each value's country — needed for fields whose prompt has genuine
    per-country rules (Section 11 finding: ~3% of Positions/Designations
    values, e.g. "President", have a different correct answer per country).
    For every other field this is off, so dedup stays value-only (cheaper,
    and correct for them) — see fields.FieldSpec.country_dependent.
    """
    use_country = country_dependent and country_column is not None
    if use_country:
        country_values = [_norm_key(v) for v in df[country_column]]
    else:
        country_values = [""] * len(df)

    # Every row's key is a (country, raw_value) pair; country is "" when
    # country-awareness isn't in play, which collapses to the old value-only
    # behavior exactly (uniqueness is then driven by raw_value alone).
    keys: list[tuple[str, str]] = [
        (country_values[i], _norm_key(v)) for i, v in enumerate(df[column])
    ]
    blanks = sum(1 for _, raw in keys if raw == "")

    # 3.4 duplicates: classify each unique non-blank (country, value) pair once.
    unique_nonblank = list(dict.fromkeys(k for k in keys if k[1] != ""))

    # Pre-flight: resolve as many values as possible from the master lookup
    # before touching the API.  Lookup hits get HIGH confidence (known-good
    # prior classifications) and are never flagged for review.
    field_lookup = _MASTER_LOOKUP.get(field_key) if field_key else None
    # (country, raw_value) -> (std_value, confidence, alternatives, reasoning)
    mapping: dict[tuple[str, str], tuple[str, str, list, str]] = {}
    mapping_sources: dict[tuple[str, str], str] = {}
    to_classify: list[tuple[str, str]] = []
    lookup_hits = 0
    alias_matches = 0
    alias_reviews = 0
    alias_deferred = 0
    similarity_predictions = 0
    semantic_retrievals = 0
    retrieval_examples: dict[
        tuple[str, str], list[tuple[str, str, float]]
    ] = {}
    evidence_notes: dict[tuple[str, str], list[str]] = {}
    forced_review: set[tuple[str, str]] = set()

    if semantic_retriever is None:
        semantic_retriever = _SEMANTIC_RETRIEVER
    if automation_policy is _USE_CONFIGURED_POLICY:
        automation_policy = _AUTOMATION_POLICY

    if field_lookup is not None:
        for k in unique_nonblank:
            country, raw = k
            decision = field_lookup.get_with_source(raw, country)
            if decision is not None:
                result, source = decision
                # Exact matches are HIGH confidence; a substantive reason with
                # reviewed/historical provenance is added to the export below.
                mapping[k] = (result, "HIGH", [], "")
                mapping_sources[k] = source
                lookup_hits += 1
            else:
                to_classify.append(k)
    else:
        to_classify = unique_nonblank

    # Pre-classify obvious system artifacts without an API call.
    # e.g. MASKED_WHOIS_DATA, NULL_VALUE — all-caps snake_case values are never
    # real business data and always map to the catch-all.
    filtered_to_classify: list[tuple[str, str]] = []
    for k in to_classify:
        _, raw = k
        if _SYSTEM_ARTIFACT_RE.match(raw):
            mapping[k] = (
                blank_fill, "LOW", [],
                f"{raw!r} appears to be a system data artifact — mapped to catch-all for review.",
            )
            mapping_sources[k] = "system_artifact"
        else:
            filtered_to_classify.append(k)
    to_classify = filtered_to_classify

    # Pre-classify data quality placeholders (N/A, null, single chars, etc.)
    # — definitively Other / Unclassified, no API call needed.
    filtered_to_classify2: list[tuple[str, str]] = []
    for k in to_classify:
        _, raw = k
        if _is_data_quality_placeholder(raw):
            mapping[k] = (
                blank_fill, "HIGH", [], "",
            )
            mapping_sources[k] = "placeholder"
        else:
            filtered_to_classify2.append(k)
    to_classify = filtered_to_classify2

    # Approved exact aliases may be accepted automatically.  Any alias result
    # involving an uncovered meaning-changing modifier remains unresolved,
    # carries explicit safety warnings into the model payload, and is forced
    # into the human-review queue even if the model sounds confident.
    if alias_matcher is not None and field_key:
        unresolved_after_aliases: list[tuple[str, str]] = []
        for k in to_classify:
            country, raw = k
            alias_result = alias_matcher.match(field_key, raw, country)
            if alias_result.outcome is MatchOutcome.MATCH:
                alias_is_automatic = (
                    automation_policy is None
                    or automation_policy.accepts_alias(field_key)
                )
                if alias_is_automatic:
                    mapping[k] = (
                        alias_result.canonical_value or blank_fill,
                        "HIGH",
                        [],
                        "",
                    )
                    mapping_sources[k] = "approved_alias"
                    alias_matches += 1
                    continue
                alias_deferred += 1
                rule = automation_policy.alias_rules.get(field_key)
                evidence_notes.setdefault(k, []).append(
                    rule.reason if rule else
                    "No measured alias automation rule exists for this field."
                )
                for item in alias_result.evidence:
                    if item.canonical_value:
                        retrieval_examples.setdefault(k, []).append((
                            item.matched_text,
                            item.canonical_value,
                            1.0,
                        ))
            if alias_result.outcome is MatchOutcome.REVIEW:
                alias_reviews += 1
                forced_review.add(k)
                evidence_notes[k] = list(alias_result.warnings)
                for item in alias_result.evidence:
                    if item.canonical_value:
                        retrieval_examples.setdefault(k, []).append((
                            item.matched_text,
                            item.canonical_value,
                            1.0,
                        ))
            unresolved_after_aliases.append(k)
        to_classify = unresolved_after_aliases

    # Predict only near-identical variants with strong label agreement. Broader
    # matches are retained as approved examples for Claude. This runs after the
    # artifact/placeholder filters so noisy no-data values can never borrow a
    # real business classification from a vaguely similar lookup entry.
    if field_lookup is not None:
        still_unresolved: list[tuple[str, str]] = []
        for k in to_classify:
            country, raw = k
            calibrated_evidence = summarize_similarity_matches(
                field_lookup.similar(
                    raw,
                    country,
                    limit=8,
                    min_score=0.0,
                )
            )
            calibrated_accept = (
                isinstance(automation_policy, AutomationPolicy)
                and automation_policy.accepts_similarity(
                    field_key or "",
                    calibrated_evidence,
                )
            )
            prediction = None
            if not calibrated_accept and allow_similarity_predictions:
                prediction = field_lookup.predict_similar(raw, country)

            if calibrated_accept:
                rule = automation_policy.similarity_rule(field_key or "")
                reasoning = (
                    "Automatically mapped by a validation-backed field policy: "
                    f"score={calibrated_evidence.score:.0%}, "
                    f"agreement={calibrated_evidence.agreement:.0%}, "
                    f"margin={calibrated_evidence.margin:.0%}; "
                    f"held-out precision={rule.validation_precision:.1%}."
                )
                mapping[k] = (
                    calibrated_evidence.predicted_value,
                    "HIGH",
                    [],
                    reasoning,
                )
                mapping_sources[k] = "similarity"
                similarity_predictions += 1
            elif prediction is not None:
                example = prediction.matches[0]
                confidence = "HIGH" if prediction.score == 1.0 else "MEDIUM"
                reasoning = (
                    f"Opt-in legacy prediction from approved mapping {example.raw_value!r} "
                    f"({prediction.score:.0%} text similarity)."
                )
                mapping[k] = (
                    prediction.standardized_value, confidence, [], reasoning,
                )
                mapping_sources[k] = "similarity"
                similarity_predictions += 1
            else:
                examples = field_lookup.similar(raw, country)
                if examples:
                    retrieval_examples.setdefault(k, []).extend(
                        (m.raw_value, m.standardized_value, m.score)
                        for m in examples
                    )
                still_unresolved.append(k)
        to_classify = still_unresolved

    # Hybrid semantic retrieval is evidence-only.  It never writes directly to
    # ``mapping``.  Competing nearby labels are made explicit and force human
    # review; other evidence simply helps the classifier apply the taxonomy.
    if semantic_retriever is not None and field_key:
        for k in to_classify:
            country, raw = k
            retrieved = semantic_retriever.retrieve(
                raw,
                field_key=field_key,
                country=country,
            )
            if not retrieved.evidence and not retrieved.conflicts:
                continue
            semantic_retrievals += 1
            combined_evidence = list(retrieved.evidence)
            for conflict in retrieved.conflicts:
                combined_evidence.extend(conflict.evidence)
            retrieval_examples.setdefault(k, []).extend(
                (
                    f"[Country: {item.country}] {item.source_value}"
                    if item.country else item.source_value,
                    item.label,
                    item.score,
                )
                for item in combined_evidence
            )
            if retrieved.has_conflicts:
                labels = ", ".join(conflict.label for conflict in retrieved.conflicts)
                evidence_notes.setdefault(k, []).append(
                    "Hybrid retrieval found competing nearby canonical labels: "
                    f"{labels}. Do not force an automatic decision."
                )
                forced_review.add(k)

    # Keep the context small and deterministic.  Duplicate evidence from the
    # lexical and semantic retrievers is collapsed, retaining its best score.
    for k, examples in list(retrieval_examples.items()):
        deduped: dict[tuple[str, str], float] = {}
        for raw_example, label, score in examples:
            identity = (raw_example, label)
            deduped[identity] = max(deduped.get(identity, 0.0), float(score))
        retrieval_examples[k] = [
            (raw_example, label, score)
            for (raw_example, label), score in sorted(
                deduped.items(),
                key=lambda item: (-item[1], item[0][1], item[0][0]),
            )[:4]
        ]

    # 4.1 chunking: never send the whole file as one call.
    warnings: list[str] = []
    failed_batches: list[run_log.BatchFailure] = []
    n_batches = 0
    retries_used = 0
    verified_decisions = 0
    verification_reviews = 0
    retrieval_assisted = sum(1 for k in to_classify if retrieval_examples.get(k))
    effective_canonical = list(canonical_values or ())
    if not effective_canonical and field_key:
        effective_canonical = list(fields.get(field_key).standard_values)

    def _on_retry(attempt: int, exc: Exception, delay: float) -> None:
        nonlocal retries_used
        retries_used += 1
        print(
            f"    [retry] batch {n_batches}: attempt {attempt} failed "
            f"({type(exc).__name__}: {exc}) — waiting {delay:.1f}s before retry"
        )

    for chunk in _chunks(to_classify, batch_size):
        n_batches += 1
        # What the model actually sees: country-prefixed when applicable,
        # otherwise identical to the old plain-value framing.
        display_values = [
            f"[Country: {country}] {raw}" if country else raw for country, raw in chunk
        ]
        approved_examples = [retrieval_examples.get(k, []) for k in chunk]
        chunk_notes = [evidence_notes.get(k, []) for k in chunk]
        try:
            # 4.2 retry/backoff wraps the whole classify call (build message +
            # API call + parse) — the API call inside is what can actually fail.
            if effective_canonical:
                request = ClassificationRequest(
                    raw_values=display_values,
                    system_prompt=system_prompt,
                    canonical_values=effective_canonical,
                    approved_examples=approved_examples,
                    evidence_notes=chunk_notes,
                    verification_policy=verification_policy,
                    high_risk_indexes=frozenset(
                        index
                        for index, k in enumerate(chunk, start=1)
                        if k in forced_review
                    ),
                )
                outcome = call_with_retry(
                    classify_request,
                    request,
                    client,
                    verification_client,
                    max_attempts=max_attempts,
                    base_delay=retry_base_delay,
                    on_retry=_on_retry,
                )
                batch = outcome.batch
                verified_decisions += sum(
                    result.decision_status == DECISION_VERIFIED
                    for result in batch.results
                )
                verification_reviews += sum(
                    result.decision_status == DECISION_HUMAN_REVIEW
                    and bool(result.verification_reason)
                    for result in batch.results
                )
            else:
                batch = call_with_retry(
                    classify_values,
                    display_values,
                    system_prompt,
                    client,
                    approved_examples,
                    None,
                    chunk_notes,
                    max_attempts=max_attempts,
                    base_delay=retry_base_delay,
                    on_retry=_on_retry,
                )
        except RetryExhaustedError as exc:
            print(f"    [FAILED] batch {n_batches} gave up after retries: {exc}")
            failed_batches.append(
                run_log.BatchFailure(batch_index=n_batches, values=list(display_values), error=str(exc))
            )
            for k in chunk:
                # "" confidence -> always flagged, regardless of ERROR_FILL's text.
                mapping[k] = (ERROR_FILL, "", [], "")
                mapping_sources[k] = "api_failure"
            continue

        warnings.extend(f"batch {n_batches}: {w}" for w in batch.warnings)
        # Align by position (guaranteed by parse_response), not by matching
        # r.raw_value text — the model sees the country-prefixed string, but
        # the mapping key must be the original (country, raw) tuple.
        for k, r in zip(chunk, batch.results):
            std_val = r.standardized_value
            confidence = r.confidence
            alternatives = r.alternatives
            reasoning = r.reasoning
            if r.verification_reason:
                reasoning = " ".join(
                    part for part in (reasoning, r.verification_reason) if part
                )
            # If the model returned a non-canonical value (e.g. echoed the
            # country-prefixed input or invented a new label), replace it with
            # the catch-all and flag for review so nothing non-standard leaks
            # into the output.
            if canonical_values and std_val and std_val not in canonical_values:
                reasoning = f"Model returned non-canonical value {std_val!r} — mapped to catch-all for review."
                std_val = blank_fill
                confidence = "LOW"
                alternatives = []
            if k in forced_review:
                safety_reason = " ".join(evidence_notes.get(k, []))
                reasoning = " ".join(
                    part for part in (
                        reasoning,
                        safety_reason,
                        "Conservative routing requires human review.",
                    )
                    if part
                )
                confidence = "LOW"
            mapping[k] = (std_val, confidence, alternatives, reasoning)
            mapping_sources[k] = "model"

    # Collect HIGH confidence API results for lookup enrichment.
    new_mappings: dict = {}
    for k in to_classify:
        entry = mapping.get(k)
        if entry is not None:
            std_val, confidence, _, _ = entry
            if (
                confidence == "HIGH"
                and std_val
                and std_val != ERROR_FILL
                and k not in forced_review
            ):
                new_mappings[k] = std_val

    # Build output columns, aligned row-for-row with the original.
    # Blanks are auto-filled with no real classification attempt — flagged too.
    # LOW:    Needs Review shows "Needs Review: Alt1? / Alt2?"; Review Reason has reasoning.
    # MEDIUM: Needs Review is blank; Review Reason has reasoning (decision support, not action required).
    # HIGH:   both new columns blank — no noise for the reviewer.
    standardized: list[str] = []
    mapping_reasons: list[str] = []
    needs_review: list[str] = []
    review_reason: list[str] = []
    for k in keys:
        if k[1] == "":
            standardized.append(blank_fill)
            mapping_reasons.append(build_mapping_reason(
                field_key=field_key,
                raw_value="",
                standardized_value=blank_fill,
                source="blank",
                country=k[0],
            ))
            needs_review.append(NEEDS_REVIEW_COLUMN)
            review_reason.append("")
            continue
        value, confidence, alternatives, reasoning = mapping.get(k, (blank_fill, "", [], ""))
        # Guard against empty values from parse failures — never write NaN.
        if not value:
            value = blank_fill
        standardized.append(value)
        mapping_reasons.append(build_mapping_reason(
            field_key=field_key,
            raw_value=k[1],
            standardized_value=value,
            source=mapping_sources.get(k, "model"),
            country=k[0],
            existing_reason=reasoning,
        ))
        if confidence in ("", "LOW"):
            alts_str = " / ".join(f"{a}?" for a in alternatives) if alternatives else ""
            needs_review.append(
                f"{NEEDS_REVIEW_COLUMN}: {alts_str}" if alts_str else NEEDS_REVIEW_COLUMN
            )
            review_reason.append(reasoning)
        elif confidence == "MEDIUM":
            needs_review.append("")
            review_reason.append(reasoning)
        else:  # HIGH
            needs_review.append("")
            review_reason.append("")

    # 3.2 passthrough + 3.3 insert next to the raw column.
    result = df.copy()
    result = result.drop(columns=[
        c for c in (
            STANDARDIZED_COLUMN,
            MAPPING_REASON_COLUMN,
            NEEDS_REVIEW_COLUMN,
            REVIEW_REASON_COLUMN,
        )
        if c in result.columns
    ])
    insert_at = result.columns.get_loc(column) + 1
    result.insert(insert_at, STANDARDIZED_COLUMN, standardized)
    result.insert(insert_at + 1, MAPPING_REASON_COLUMN, mapping_reasons)
    result.insert(insert_at + 2, NEEDS_REVIEW_COLUMN, needs_review)
    result.insert(insert_at + 3, REVIEW_REASON_COLUMN, review_reason)

    non_blank_rows = len(keys) - blanks
    stats = Stats(
        raw_column=column,
        total_rows=len(df),
        blanks=blanks,
        unique_values=len(unique_nonblank),
        duplicates_collapsed=non_blank_rows - len(unique_nonblank),
        batches=n_batches,
        batch_size=batch_size,
        api_calls_saved=(
            (non_blank_rows - len(unique_nonblank))
            + blanks + lookup_hits + alias_matches + similarity_predictions
        ),
        lookup_hits=lookup_hits,
        alias_matches=alias_matches,
        alias_reviews=alias_reviews,
        alias_deferred=alias_deferred,
        similarity_predictions=similarity_predictions,
        retrieval_assisted=retrieval_assisted,
        semantic_retrievals=semantic_retrievals,
        verified_decisions=verified_decisions,
        verification_reviews=verification_reviews,
        flagged_count=sum(1 for v in needs_review if v.startswith(NEEDS_REVIEW_COLUMN)),
        retries_used=retries_used,
        failed_batches=failed_batches,
        warnings=warnings,
        new_mappings=new_mappings,
    )
    return result, stats


def standardize_file(
    path: Path,
    system_prompt: str,
    client,
    column: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    output_dir: Path = config.OUTPUT_DIR,
    country_dependent: bool = False,
) -> tuple[pd.DataFrame, Stats, Path]:
    df = read_table(path)
    raw_col = detect_value_column(df, column)
    country_col = detect_country_column(df) if country_dependent else None
    result, stats = standardize_dataframe(
        df, raw_col, system_prompt, client, batch_size,
        country_dependent=country_dependent, country_column=country_col,
        field_key=None,
    )
    out_path = output_dir / f"{path.stem}_standardized.xlsx"
    result.to_excel(out_path, index=False)
    return result, stats, out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 3/4/5 — standardize a real file")
    parser.add_argument(
        "--field", default=DEFAULT_FIELD, choices=sorted(fields.FIELDS),
        help="which taxonomy field to apply (looked up in the registry, src/fields.py)",
    )
    parser.add_argument("--data", type=Path, default=None,
                         help=f"defaults to {DEFAULT_DATA_FILE} if omitted")
    parser.add_argument("--prompt", type=Path, default=None,
                         help="override: use this prompt file instead of the field's registered one")
    parser.add_argument("--column", default=None, help="raw-value column (else auto-detect)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS,
                         help="max attempts per batch before giving up")
    parser.add_argument("--retry-base-delay", type=float, default=DEFAULT_RETRY_BASE_DELAY,
                         help="seconds to wait before the first retry (doubles each attempt)")
    parser.add_argument("--live", action="store_true", help="use the real Anthropic API")
    parser.add_argument(
        "--offline-semantic",
        action="store_true",
        help=(
            "exercise semantic wiring with deterministic fake embeddings; "
            "offline/test-only and not evidence of production accuracy"
        ),
    )
    parser.add_argument(
        "--allow-similarity-predictions",
        action="store_true",
        help=(
            "opt into legacy near-identical automatic predictions; disabled "
            "by default until golden-dataset acceptance thresholds are met"
        ),
    )
    parser.add_argument(
        "--verify-uncertain",
        action="store_true",
        help="run an optional second classifier pass for uncertain/high-risk decisions",
    )
    parser.add_argument(
        "--simulate-flaky", type=int, default=0, metavar="N",
        help="inject N simulated transient errors (real anthropic.RateLimitError) "
             "then succeed — demonstrates retry recovering within budget",
    )
    parser.add_argument(
        "--simulate-broken", action="store_true",
        help="inject enough simulated errors to exhaust the first batch's retries "
             "(real anthropic.InternalServerError) — demonstrates a permanently "
             "failed batch being logged distinctly while the rest of the run completes",
    )
    parser.add_argument(
        "--no-ticket", action="store_true",
        help="skip generating the ready-to-paste Jira ticket content after the run",
    )
    args = parser.parse_args()

    if args.offline_semantic:
        configure_embedding_provider(DeterministicHashEmbeddingProvider())

    spec = fields.get(args.field)
    data_path = args.data or DEFAULT_DATA_FILE
    blank_fill = spec.standard_values[-1]  # this field's own catch-all value

    if not data_path.exists():
        print(f"Data file not found: {data_path}")
        print("Generate samples first: .venv\\Scripts\\python.exe src\\_make_sample_data.py")
        return 1

    df = read_table(data_path)
    original_columns = list(df.columns)

    try:
        raw_col = detect_value_column(df, args.column)
    except ValueError as exc:
        print(f"[!] {exc}")
        return 1

    if args.prompt:
        prompt_path = args.prompt
        # Match spec.load_prompt()'s behavior: append the Step 8 confidence
        # contract even for an overridden prompt file, since parse_response
        # now expects every response in that format.
        system_prompt = prompt_path.read_text(encoding="utf-8").rstrip() + "\n\n" + CONFIDENCE_ADDENDUM
    else:
        prompt_path = spec.prompt_path
        system_prompt = spec.load_prompt()
    client = RealClaudeClient() if args.live else MockClaudeClient(field_key=args.field)

    if args.simulate_broken:
        # Exactly enough failures to exhaust the FIRST batch's retry budget,
        # then let every later batch through — shows the run survives one
        # bad batch instead of crashing entirely.
        client = FlakyClient(client, fail_times=args.max_attempts, error_factory=server_error)
    elif args.simulate_flaky:
        client = FlakyClient(client, fail_times=args.simulate_flaky, error_factory=rate_limit_error)

    print(f"Field            : {spec.display_name}  (key: {spec.key})")
    if spec.notes:
        print(f"  NOTE: {spec.notes}")
    print(f"Loaded {len(df)} rows from {data_path.name}")
    print(f"  columns          : {original_columns}")
    print(f"  raw-value column : {raw_col!r}  "
          f"({'you specified' if args.column else 'auto-detected'})")
    print(f"  prompt file      : {prompt_path.name}")
    print(f"  client           : {client.name}")
    print(f"  batch size       : {args.batch_size}")
    print(f"  retry policy     : max {args.max_attempts} attempts, "
          f"{args.retry_base_delay}s base backoff")
    if not args.live:
        print("  NOTE: values are SIMULATED (mock). --live uses the real API; "
              "the file handling is identical.")
        if args.field not in ("positions_designations", "business_legal_form"):
            print(f"  NOTE: mock has no keyword heuristic for {args.field!r} — every "
                  f"value will fall back to {blank_fill!r}. This proves the pipeline "
                  "(field lookup, batching, retry, logging) works for this field; "
                  "real classification needs --live.")

    country_col = detect_country_column(df) if spec.country_dependent else None
    if spec.country_dependent:
        if country_col:
            print(f"  country column   : {country_col!r}  "
                  "(classifying per (country, value) pair — see field notes)")
        else:
            print("  NOTE: this field is country-dependent but no country column was "
                  "found — falling back to value-only classification (same as before).")

    result, stats = standardize_dataframe(
        df, raw_col, system_prompt, client,
        batch_size=args.batch_size,
        blank_fill=blank_fill,
        max_attempts=args.max_attempts,
        retry_base_delay=args.retry_base_delay,
        country_dependent=spec.country_dependent,
        country_column=country_col,
        field_key=spec.key,
        canonical_values=list(spec.standard_values),
        allow_similarity_predictions=args.allow_similarity_predictions,
        verification_policy=(
            VerificationPolicy() if args.verify_uncertain else None
        ),
    )

    # Show a preview with the raw column and the new columns side by side.
    preview_cols = [
        raw_col,
        STANDARDIZED_COLUMN,
        MAPPING_REASON_COLUMN,
        NEEDS_REVIEW_COLUMN,
        REVIEW_REASON_COLUMN,
    ]
    if "country" in result.columns:
        preview_cols = ["country"] + preview_cols
    print("\nPreview (first 12 rows):")
    with pd.option_context("display.max_rows", 12, "display.width", 120):
        print(result[preview_cols].head(12).to_string(index=False))

    # 3.2 verify passthrough — no original column lost or altered in place.
    passthrough_ok = all(c in result.columns for c in original_columns)
    inserted_right = list(result.columns).index(STANDARDIZED_COLUMN) == \
        list(result.columns).index(raw_col) + 1

    out_path = config.OUTPUT_DIR / f"{data_path.stem}_standardized.xlsx"
    result.to_excel(out_path, index=False)

    print("\n" + "-" * 68)
    print(f"  total rows            : {stats.total_rows}")
    print(f"  blank/empty raw       : {stats.blanks}  (filled as {blank_fill!r}, no API call)")
    print(f"  unique values         : {stats.unique_values}")
    print(f"  lookup hits           : {stats.lookup_hits}  (resolved from master table, no API call)")
    print(f"  approved aliases      : {stats.alias_matches}  (safe exact aliases, no API call)")
    print(f"  aliases sent onward   : {stats.alias_deferred}  (below measured field evidence requirement)")
    print(f"  alias safety reviews  : {stats.alias_reviews}  (modifier cases sent onward and forced to review)")
    print(f"  similarity predictions: {stats.similarity_predictions}  (near-identical approved mappings)")
    print(f"  retrieval-assisted    : {stats.retrieval_assisted}  (classifier received approved examples)")
    print(f"  semantic evidence     : {stats.semantic_retrievals}  (evidence only; never auto-classified)")
    print(f"  verified decisions    : {stats.verified_decisions}  (optional second pass agreed)")
    print(f"  verification reviews  : {stats.verification_reviews}  (second pass inconclusive/disagreed)")
    print(
        f"  sent to classifier    : "
        f"{stats.unique_values - stats.lookup_hits - stats.alias_matches - stats.similarity_predictions}"
    )
    print(f"  duplicates reused     : {stats.duplicates_collapsed}")
    print(f"  API batches           : {stats.batches}  (size {stats.batch_size})")
    print(f"  rows needing no call  : {stats.api_calls_saved}  (dupes + blanks + lookup/prediction hits)")
    print(f"  flagged for review    : {stats.flagged_count}  "
          f"(LOW/missing confidence, blanks, or API failures — see {NEEDS_REVIEW_COLUMN!r} + {REVIEW_REASON_COLUMN!r} columns)")
    print(f"  all columns preserved : {'YES' if passthrough_ok else 'NO'}")
    print(f"  new column placed     : {'next to raw column' if inserted_right else 'MISPLACED'}")

    # 4.3 run log — write the JSONL record and print its summary.
    record = run_log.new_record(
        source_file=str(data_path),
        raw_column=raw_col,
        total_rows=stats.total_rows,
        blank_rows=stats.blanks,
        unique_values_sent=stats.unique_values,
        duplicates_reused=stats.duplicates_collapsed,
        batches_total=stats.batches,
        batches_failed=len(stats.failed_batches),
        retries_used=stats.retries_used,
        flagged_count=stats.flagged_count,
        mismatches=stats.warnings,
        failures=stats.failed_batches,
    )
    run_log.write(record)
    print(f"  retries used          : {stats.retries_used}")
    print(f"  batches failed        : {len(stats.failed_batches)}")
    if stats.failed_batches:
        for f in stats.failed_batches:
            preview = ", ".join(f.values[:3]) + ("…" if len(f.values) > 3 else "")
            print(f"      - batch {f.batch_index} [{preview}] -> marked {ERROR_FILL!r}")
    print(f"  run logged to         : {run_log.LOG_FILE}")

    all_ok = stats.ok and passthrough_ok and inserted_right
    print(f"  status                : {'PASS' if all_ok else 'WARNINGS'}")
    if not all_ok:
        for w in stats.warnings:
            print(f"      - {w}")
    print(f"  saved                 : {out_path}")
    print("-" * 68)

    # Section 5 item 8 — ready-to-paste Jira ticket content for the
    # engineering handoff (NOT a live Jira API call — see Section 6).
    if not args.no_ticket:
        countries = find_countries(df)
        ticket_text = build_ticket_text(spec.display_name, raw_col, countries, out_path.name)
        ticket_path = config.OUTPUT_DIR / f"{data_path.stem}_jira_ticket.txt"
        ticket_path.write_text(ticket_text, encoding="utf-8")
        print("\nJira ticket content (ready to paste):")
        print("=" * 68)
        print(ticket_text)
        print("=" * 68)
        print(f"Saved to: {ticket_path}")

    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
