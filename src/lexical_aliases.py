"""Conservative, reviewable lexical aliases for classification pre-processing.

This module intentionally performs no fuzzy or semantic matching.  It accepts
only exact matches after harmless lexical normalization (case, whitespace,
accents, and punctuation) and explicitly configured abbreviation expansion.
Meaning-changing modifiers turn a possible base match into a review result
unless the complete phrase is itself an approved alias that covers the
modifier.

The component is isolated from the file-standardization pipeline.  See
``docs/lexical_aliases.md`` for the public integration contract.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional


DEFAULT_RULES_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "lexical_aliases.json"
)


class RuleConflictError(ValueError):
    """Raised when alias configuration is contradictory or invalid."""


class MatchOutcome(str, Enum):
    """The only three outcomes returned by :meth:`LexicalAliasMatcher.match`."""

    MATCH = "match"
    REVIEW = "review"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class AliasRule:
    """One approved exact alias, optionally limited to specific countries."""

    field_key: str
    alias: str
    normalized_alias: str
    canonical_value: str
    kind: str
    expansion: str
    countries: tuple[str, ...]
    covers_modifiers: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class ModifierRule:
    """A word or phrase that can change the meaning of a base alias."""

    field_key: str
    phrase: str
    normalized_phrase: str
    warning: str


@dataclass(frozen=True)
class LexicalEvidence:
    """Auditable evidence explaining a lexical decision."""

    kind: str
    matched_text: str
    detail: str
    canonical_value: Optional[str] = None
    country: str = ""


@dataclass(frozen=True)
class LexicalResult:
    """Result from a conservative lexical lookup.

    ``canonical_value`` is populated only for safe ``MATCH`` outcomes.
    ``suggested_value`` may be populated for ``REVIEW`` outcomes, but callers
    must not treat it as an accepted classification.
    """

    outcome: MatchOutcome
    field_key: str
    raw_value: str
    normalized_value: str
    country: str
    canonical_value: Optional[str] = None
    suggested_value: Optional[str] = None
    evidence: tuple[LexicalEvidence, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def safe_to_accept(self) -> bool:
        """Whether the result can be used without model or human review."""

        return self.outcome is MatchOutcome.MATCH


def normalize_lexical(value: object) -> str:
    """Normalize harmless formatting without guessing at semantic similarity.

    Normalization is case-insensitive, accent-insensitive, and treats
    punctuation as token separators.  Explicitly punctuated initialisms such
    as ``C.E.O.`` normalize to ``ceo``; whitespace-separated letters remain
    separate so arbitrary text such as ``C E O`` is not silently promoted to
    an approved abbreviation.  No stemming, edit-distance matching, or token
    reordering is performed.
    """

    if value is None:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    # Collapse only initialisms whose letters are explicitly joined by safe
    # abbreviation punctuation.  Plain spaces are deliberately excluded.
    punctuated_initials = re.compile(
        r"(?<!\w)(?:[^\W_][._-]){1,}[^\W_](?:[._-])?(?!\w)",
        flags=re.UNICODE,
    )
    without_marks = punctuated_initials.sub(
        lambda match: re.sub(r"[._-]", "", match.group(0)),
        without_marks,
    )
    return " ".join(
        re.sub(r"[\W_]+", " ", without_marks, flags=re.UNICODE).split()
    )


class LexicalAliasMatcher:
    """Exact, field-specific alias matcher with modifier safeguards."""

    def __init__(
        self,
        *,
        aliases: tuple[AliasRule, ...],
        modifiers: tuple[ModifierRule, ...],
        country_aliases: Mapping[str, str],
    ) -> None:
        self.aliases = aliases
        self.modifiers = modifiers
        self._country_aliases = dict(country_aliases)
        self._alias_index: dict[tuple[str, str], list[AliasRule]] = {}
        self._modifier_index: dict[str, tuple[ModifierRule, ...]] = {}

        for rule in aliases:
            self._alias_index.setdefault(
                (rule.field_key, rule.normalized_alias), []
            ).append(rule)
        for field_key in {rule.field_key for rule in modifiers}:
            field_rules = [
                rule for rule in modifiers if rule.field_key == field_key
            ]
            field_rules.sort(
                key=lambda rule: (-len(rule.normalized_phrase.split()), rule.phrase)
            )
            self._modifier_index[field_key] = tuple(field_rules)

    @classmethod
    def from_file(cls, path: str | Path) -> "LexicalAliasMatcher":
        """Load and validate a UTF-8 JSON rule file."""

        rule_path = Path(path)
        with rule_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LexicalAliasMatcher":
        """Build a matcher from a dictionary, rejecting conflicting rules."""

        issues: list[str] = []
        if payload.get("schema_version") != 1:
            issues.append("schema_version must be 1")

        raw_country_aliases = payload.get("country_aliases", {})
        if not isinstance(raw_country_aliases, Mapping):
            issues.append("country_aliases must be an object")
            raw_country_aliases = {}

        country_aliases: dict[str, str] = {}
        for raw_alias, raw_country in raw_country_aliases.items():
            alias_n = normalize_lexical(raw_alias)
            country_n = normalize_lexical(raw_country)
            if not alias_n or not country_n:
                issues.append("country aliases and canonical countries must be non-empty")
                continue
            previous = country_aliases.get(alias_n)
            if previous is not None and previous != country_n:
                issues.append(
                    f"country alias {raw_alias!r} conflicts: "
                    f"{previous!r} versus {country_n!r}"
                )
            country_aliases[alias_n] = country_n
            country_aliases.setdefault(country_n, country_n)

        fields_payload = payload.get("fields", {})
        if not isinstance(fields_payload, Mapping):
            issues.append("fields must be an object")
            fields_payload = {}

        aliases: list[AliasRule] = []
        modifiers: list[ModifierRule] = []
        alias_scopes: dict[tuple[str, str, str], str] = {}
        modifier_keys: dict[tuple[str, str], str] = {}

        def normalize_country(value: object) -> str:
            country_n = normalize_lexical(value)
            return country_aliases.get(country_n, country_n)

        for field_key, raw_field in fields_payload.items():
            if not isinstance(raw_field, Mapping):
                issues.append(f"field {field_key!r} must be an object")
                continue

            canonical_values = raw_field.get("canonical_values", [])
            if (
                not isinstance(canonical_values, list)
                or not canonical_values
                or any(not isinstance(value, str) or not value for value in canonical_values)
            ):
                issues.append(
                    f"field {field_key!r} canonical_values must be a non-empty string list"
                )
                canonical_set: set[str] = set()
            else:
                canonical_set = set(canonical_values)
                if len(canonical_set) != len(canonical_values):
                    issues.append(
                        f"field {field_key!r} contains duplicate canonical values"
                    )

            field_modifiers: set[str] = set()
            raw_modifiers = raw_field.get("modifier_rules", [])
            if not isinstance(raw_modifiers, list):
                issues.append(f"field {field_key!r} modifier_rules must be a list")
                raw_modifiers = []
            for raw_modifier in raw_modifiers:
                if not isinstance(raw_modifier, Mapping):
                    issues.append(f"field {field_key!r} has a non-object modifier rule")
                    continue
                phrase = str(raw_modifier.get("phrase", "")).strip()
                warning = str(raw_modifier.get("warning", "")).strip()
                phrase_n = normalize_lexical(phrase)
                if not phrase_n or not warning:
                    issues.append(
                        f"field {field_key!r} modifier rules require phrase and warning"
                    )
                    continue
                key = (field_key, phrase_n)
                previous = modifier_keys.get(key)
                if previous is not None:
                    qualifier = "conflicts" if previous != warning else "is duplicated"
                    issues.append(
                        f"modifier {phrase!r} for {field_key!r} {qualifier}"
                    )
                    continue
                modifier_keys[key] = warning
                field_modifiers.add(phrase_n)
                modifiers.append(
                    ModifierRule(
                        field_key=field_key,
                        phrase=phrase,
                        normalized_phrase=phrase_n,
                        warning=warning,
                    )
                )

            raw_aliases = raw_field.get("aliases", [])
            if not isinstance(raw_aliases, list):
                issues.append(f"field {field_key!r} aliases must be a list")
                raw_aliases = []
            for raw_rule in raw_aliases:
                if not isinstance(raw_rule, Mapping):
                    issues.append(f"field {field_key!r} has a non-object alias rule")
                    continue
                alias = str(raw_rule.get("alias", "")).strip()
                alias_n = normalize_lexical(alias)
                target = str(raw_rule.get("canonical_value", "")).strip()
                kind = str(raw_rule.get("kind", "alias")).strip()
                expansion = str(raw_rule.get("expansion", "")).strip()
                note = str(raw_rule.get("note", "")).strip()
                raw_countries = raw_rule.get("countries", [])
                raw_covers = raw_rule.get("covers_modifiers", [])
                if not isinstance(raw_countries, list) or not all(
                    isinstance(country, str) for country in raw_countries
                ):
                    issues.append(
                        f"alias {alias!r} for {field_key!r} countries must be a string list"
                    )
                    raw_countries = []
                if not isinstance(raw_covers, list) or not all(
                    isinstance(modifier, str) for modifier in raw_covers
                ):
                    issues.append(
                        f"alias {alias!r} for {field_key!r} "
                        "covers_modifiers must be a string list"
                    )
                    raw_covers = []

                countries = tuple(normalize_country(country) for country in raw_countries)
                covers = tuple(normalize_lexical(modifier) for modifier in raw_covers)
                if not alias_n:
                    issues.append(f"field {field_key!r} contains an empty alias")
                    continue
                if target not in canonical_set:
                    issues.append(
                        f"alias {alias!r} for {field_key!r} has invalid canonical "
                        f"value {target!r}"
                    )
                if kind not in {"alias", "abbreviation"}:
                    issues.append(
                        f"alias {alias!r} for {field_key!r} has invalid kind {kind!r}"
                    )
                if kind == "abbreviation" and not expansion:
                    issues.append(
                        f"abbreviation {alias!r} for {field_key!r} requires expansion"
                    )
                for covered in covers:
                    if covered not in field_modifiers:
                        issues.append(
                            f"alias {alias!r} covers undeclared modifier {covered!r}"
                        )
                    if not _contains_phrase(alias_n, covered):
                        issues.append(
                            f"alias {alias!r} does not contain covered modifier {covered!r}"
                        )

                scopes = countries or ("",)
                for scope in scopes:
                    key = (field_key, alias_n, scope)
                    previous = alias_scopes.get(key)
                    if previous is not None:
                        qualifier = "conflicts" if previous != target else "is duplicated"
                        issues.append(
                            f"alias {alias!r} for {field_key!r} in "
                            f"{scope or 'global'!r} {qualifier}: "
                            f"{previous!r} versus {target!r}"
                        )
                    else:
                        alias_scopes[key] = target

                aliases.append(
                    AliasRule(
                        field_key=field_key,
                        alias=alias,
                        normalized_alias=alias_n,
                        canonical_value=target,
                        kind=kind,
                        expansion=expansion,
                        countries=countries,
                        covers_modifiers=covers,
                        note=note,
                    )
                )

        if issues:
            joined = "\n- ".join(sorted(set(issues)))
            raise RuleConflictError(f"Invalid lexical alias configuration:\n- {joined}")

        return cls(
            aliases=tuple(aliases),
            modifiers=tuple(modifiers),
            country_aliases=country_aliases,
        )

    def match(
        self,
        field_key: str,
        raw_value: object,
        country: object = "",
    ) -> LexicalResult:
        """Return a safe match, review suggestion, or no-match decision.

        Callers may automatically use only results whose ``safe_to_accept`` is
        true.  ``REVIEW`` outcomes deliberately leave ``canonical_value`` empty.
        """

        raw_text = "" if raw_value is None else str(raw_value)
        value_n = normalize_lexical(raw_value)
        country_n = self._normalize_country(country)
        modifiers = tuple(
            rule
            for rule in self._modifier_index.get(field_key, ())
            if _contains_phrase(value_n, rule.normalized_phrase)
        )
        exact = self._select_alias(field_key, value_n, country_n)

        if exact is not None:
            uncovered = tuple(
                modifier
                for modifier in modifiers
                if modifier.normalized_phrase not in exact.covers_modifiers
            )
            evidence = [self._alias_evidence(exact, country_n)]
            evidence.extend(self._modifier_evidence(rule) for rule in modifiers)
            if uncovered:
                warnings = tuple(rule.warning for rule in uncovered) + (
                    "The full alias does not explicitly approve every detected "
                    "meaning-changing modifier.",
                )
                return LexicalResult(
                    outcome=MatchOutcome.REVIEW,
                    field_key=field_key,
                    raw_value=raw_text,
                    normalized_value=value_n,
                    country=country_n,
                    suggested_value=exact.canonical_value,
                    evidence=tuple(evidence),
                    warnings=warnings,
                )
            return LexicalResult(
                outcome=MatchOutcome.MATCH,
                field_key=field_key,
                raw_value=raw_text,
                normalized_value=value_n,
                country=country_n,
                canonical_value=exact.canonical_value,
                evidence=tuple(evidence),
            )

        if modifiers:
            base_n = _remove_phrases(
                value_n, [rule.normalized_phrase for rule in modifiers]
            )
            base = self._select_alias(field_key, base_n, country_n)
            evidence = [self._modifier_evidence(rule) for rule in modifiers]
            if base is not None:
                evidence.append(self._alias_evidence(base, country_n, kind="base_alias"))
            warnings = tuple(rule.warning for rule in modifiers) + (
                "A meaning-changing modifier prevents automatic alias acceptance.",
            )
            return LexicalResult(
                outcome=MatchOutcome.REVIEW,
                field_key=field_key,
                raw_value=raw_text,
                normalized_value=value_n,
                country=country_n,
                suggested_value=base.canonical_value if base is not None else None,
                evidence=tuple(evidence),
                warnings=warnings,
            )

        return LexicalResult(
            outcome=MatchOutcome.NO_MATCH,
            field_key=field_key,
            raw_value=raw_text,
            normalized_value=value_n,
            country=country_n,
        )

    def _normalize_country(self, country: object) -> str:
        country_n = normalize_lexical(country)
        return self._country_aliases.get(country_n, country_n)

    def _select_alias(
        self,
        field_key: str,
        normalized_value: str,
        country: str,
    ) -> Optional[AliasRule]:
        candidates = self._alias_index.get((field_key, normalized_value), [])
        country_specific = [
            rule for rule in candidates if country and country in rule.countries
        ]
        if country_specific:
            return country_specific[0]
        return next((rule for rule in candidates if not rule.countries), None)

    @staticmethod
    def _modifier_evidence(rule: ModifierRule) -> LexicalEvidence:
        return LexicalEvidence(
            kind="modifier",
            matched_text=rule.phrase,
            detail=rule.warning,
        )

    @staticmethod
    def _alias_evidence(
        rule: AliasRule,
        country: str,
        *,
        kind: str = "alias",
    ) -> LexicalEvidence:
        detail_parts = [f"approved {rule.kind}"]
        if rule.expansion:
            detail_parts.append(f"expands to {rule.expansion!r}")
        if rule.note:
            detail_parts.append(rule.note)
        return LexicalEvidence(
            kind=kind,
            matched_text=rule.alias,
            detail="; ".join(detail_parts),
            canonical_value=rule.canonical_value,
            country=country if rule.countries else "",
        )


def load_default_matcher() -> LexicalAliasMatcher:
    """Load the version-controlled default alias and safeguard rules."""

    return LexicalAliasMatcher.from_file(DEFAULT_RULES_FILE)


def _contains_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    return f" {phrase} " in f" {text} "


def _remove_phrases(text: str, phrases: list[str]) -> str:
    result = f" {text} "
    for phrase in sorted(set(phrases), key=lambda item: -len(item.split())):
        result = result.replace(f" {phrase} ", " ")
        result = f" {' '.join(result.split())} "
    return " ".join(result.split())
