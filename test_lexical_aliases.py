"""Deterministic tests for the isolated lexical alias/safeguard component."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from lexical_aliases import (  # noqa: E402
    DEFAULT_RULES_FILE,
    LexicalAliasMatcher,
    MatchOutcome,
    RuleConflictError,
    load_default_matcher,
    normalize_lexical,
)


class LexicalAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matcher = load_default_matcher()

    def test_case_whitespace_and_punctuation_are_harmless(self) -> None:
        result = self.matcher.match(
            "positions_designations", "  c.E.o.  ", "France"
        )
        self.assertTrue(result.safe_to_accept)
        self.assertEqual(result.canonical_value, "Executive Management")
        self.assertEqual(result.normalized_value, "ceo")

    def test_hyphenated_approved_phrase_matches(self) -> None:
        result = self.matcher.match(
            "positions_designations", "NON EXECUTIVE-DIRECTOR"
        )
        self.assertTrue(result.safe_to_accept)
        self.assertEqual(result.canonical_value, "Board Member")
        self.assertTrue(any(item.kind == "modifier" for item in result.evidence))

    def test_abbreviation_returns_expansion_evidence(self) -> None:
        result = self.matcher.match("business_legal_form", "L.L.C.")
        self.assertEqual(result.canonical_value, "Company")
        self.assertIn("Limited Liability Company", result.evidence[0].detail)

    def test_field_specific_aliases_do_not_leak(self) -> None:
        positions = self.matcher.match("positions_designations", "UBO")
        brn = self.matcher.match("brn_type", "UBO")
        self.assertEqual(positions.canonical_value, "Owner / Controller")
        self.assertEqual(brn.outcome, MatchOutcome.NO_MATCH)

    def test_unknown_and_fuzzy_typo_are_not_accepted(self) -> None:
        self.assertEqual(
            self.matcher.match("positions_designations", "CFOO").outcome,
            MatchOutcome.NO_MATCH,
        )
        self.assertEqual(
            self.matcher.match("positions_designations", "mystery role").outcome,
            MatchOutcome.NO_MATCH,
        )

    def test_country_specific_alias_overrides_global(self) -> None:
        uk = self.matcher.match(
            "positions_designations", "CEO", "United Kingdom"
        )
        france = self.matcher.match("positions_designations", "CEO", "France")
        self.assertEqual(uk.canonical_value, "Board Member")
        self.assertEqual(france.canonical_value, "Executive Management")
        self.assertEqual(uk.evidence[0].country, "united kingdom")

    def test_country_abbreviation_is_supported(self) -> None:
        result = self.matcher.match("positions_designations", "M.D.", "GB")
        self.assertEqual(result.canonical_value, "Board Member")

    def test_country_rules_do_not_borrow_from_other_countries(self) -> None:
        result = self.matcher.match("positions_designations", "MD", "Canada")
        self.assertEqual(result.canonical_value, "Executive Management")
        self.assertEqual(result.evidence[0].country, "")

    def test_former_title_is_review_only(self) -> None:
        result = self.matcher.match(
            "positions_designations", "Former Director"
        )
        self.assertEqual(result.outcome, MatchOutcome.REVIEW)
        self.assertFalse(result.safe_to_accept)
        self.assertIsNone(result.canonical_value)
        self.assertEqual(result.suggested_value, "Director")
        self.assertTrue(result.warnings)

    def test_temporary_and_subordinate_modifiers_are_review_only(self) -> None:
        for title in (
            "Acting CEO",
            "Assistant Director",
            "Deputy Director",
            "Interim CEO",
            "Resigned Director",
        ):
            with self.subTest(title=title):
                result = self.matcher.match("positions_designations", title)
                self.assertEqual(result.outcome, MatchOutcome.REVIEW)
                self.assertIsNone(result.canonical_value)

    def test_modifier_suggestion_remains_country_aware(self) -> None:
        uk = self.matcher.match(
            "positions_designations", "Acting CEO", "United Kingdom"
        )
        france = self.matcher.match(
            "positions_designations", "Acting CEO", "France"
        )
        self.assertEqual(uk.suggested_value, "Board Member")
        self.assertEqual(france.suggested_value, "Executive Management")
        self.assertIsNone(uk.canonical_value)

    def test_unreviewed_legal_form_combinations_are_not_forced(self) -> None:
        cases = {
            "Foreign LLC": "Company",
            "Branch Company": "Company",
            "Non-Profit Company": "Company",
        }
        for value, suggestion in cases.items():
            with self.subTest(value=value):
                result = self.matcher.match("business_legal_form", value)
                self.assertEqual(result.outcome, MatchOutcome.REVIEW)
                self.assertEqual(result.suggested_value, suggestion)
                self.assertIsNone(result.canonical_value)

    def test_reviewed_modifier_phrases_are_safe(self) -> None:
        cases = {
            "Branch": "Foreign Entity / Branch",
            "Foreign Company": "Foreign Entity / Branch",
            "Nonprofit": "Non-Profit / Cooperative",
        }
        for value, canonical in cases.items():
            with self.subTest(value=value):
                result = self.matcher.match("business_legal_form", value)
                self.assertTrue(result.safe_to_accept)
                self.assertEqual(result.canonical_value, canonical)

    def test_same_word_can_be_safe_in_another_field(self) -> None:
        result = self.matcher.match("directors_officers_status", "Former")
        self.assertTrue(result.safe_to_accept)
        self.assertEqual(result.canonical_value, "Resigned")

    def test_modifier_without_base_alias_still_requests_review(self) -> None:
        result = self.matcher.match(
            "positions_designations", "Former Mystery Function"
        )
        self.assertEqual(result.outcome, MatchOutcome.REVIEW)
        self.assertIsNone(result.suggested_value)
        self.assertTrue(any(item.kind == "modifier" for item in result.evidence))

    def test_all_ten_fields_have_at_least_one_working_alias(self) -> None:
        cases = {
            "positions_designations": ("CFO", "Executive Management"),
            "business_legal_form": ("LLP", "Partnership"),
            "business_status": ("Good Standing", "Active"),
            "psc_beneficiary_type": ("UBO", "Owner / Beneficial Owner"),
            "brn_type": ("TIN", "Tax ID Number"),
            "directors_officers_type": ("Corporate Director", "Business"),
            "business_entity_type": ("Natural Person", "Individual"),
            "ownership_relationship_type": (
                "Corporate Entity Beneficial Owner",
                "Business",
            ),
            "directors_officers_status": ("Serving", "Active"),
            "ownership_relationship_status": ("Pending", "Pending / Insolvency"),
        }
        for field_key, (raw, canonical) in cases.items():
            with self.subTest(field_key=field_key):
                result = self.matcher.match(field_key, raw)
                self.assertEqual(result.canonical_value, canonical)

    def test_conflicting_aliases_are_rejected(self) -> None:
        payload = self._payload()
        payload["fields"]["business_status"]["aliases"].append(
            {"alias": "Live", "canonical_value": "Inactive"}
        )
        with self.assertRaisesRegex(RuleConflictError, "conflicts"):
            LexicalAliasMatcher.from_dict(payload)

    def test_country_override_is_not_a_configuration_conflict(self) -> None:
        payload = {
            "schema_version": 1,
            "country_aliases": {"UK": "United Kingdom"},
            "fields": {
                "test": {
                    "canonical_values": ["A", "B"],
                    "modifier_rules": [],
                    "aliases": [
                        {"alias": "X", "canonical_value": "A"},
                        {
                            "alias": "X",
                            "canonical_value": "B",
                            "countries": ["United Kingdom"],
                        },
                    ],
                }
            },
        }
        matcher = LexicalAliasMatcher.from_dict(payload)
        self.assertEqual(matcher.match("test", "X").canonical_value, "A")
        self.assertEqual(
            matcher.match("test", "X", "UK").canonical_value, "B"
        )

    def test_conflicting_modifier_rules_are_rejected(self) -> None:
        payload = self._payload()
        payload["fields"]["positions_designations"]["modifier_rules"].append(
            {"phrase": "acting", "warning": "A contradictory warning."}
        )
        with self.assertRaisesRegex(RuleConflictError, "modifier .* conflicts"):
            LexicalAliasMatcher.from_dict(payload)

    def test_invalid_canonical_target_is_rejected(self) -> None:
        payload = self._payload()
        payload["fields"]["brn_type"]["aliases"].append(
            {"alias": "BAD", "canonical_value": "Invented Value"}
        )
        with self.assertRaisesRegex(RuleConflictError, "invalid canonical value"):
            LexicalAliasMatcher.from_dict(payload)

    def test_normalizer_does_not_reorder_or_fuzzy_match(self) -> None:
        self.assertEqual(normalize_lexical("  Députy---Director "), "deputy director")
        self.assertEqual(normalize_lexical("C.E.O."), "ceo")
        self.assertEqual(normalize_lexical("C E O"), "c e o")
        self.assertEqual(
            self.matcher.match("positions_designations", "C E O").outcome,
            MatchOutcome.NO_MATCH,
        )
        self.assertNotEqual(
            normalize_lexical("Director Deputy"),
            normalize_lexical("Deputy Director"),
        )

    @staticmethod
    def _payload() -> dict:
        with DEFAULT_RULES_FILE.open("r", encoding="utf-8") as handle:
            return copy.deepcopy(json.load(handle))


if __name__ == "__main__":
    unittest.main(verbosity=2)
