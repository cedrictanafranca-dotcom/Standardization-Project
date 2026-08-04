"""Regression tests for human-reviewed exact mapping overrides."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from master_lookup import load_lookup  # noqa: E402


REVIEWED_CASES = {
    ("positions_designations", "Italy", "Associate"): "Other / Unclassified",
    ("positions_designations", "United Kingdom", "WATER INDUSTRY CHIEF EXECUTIVE"): "Executive Management",
    ("positions_designations", "Indonesia", "Company Secretary"): "Other / Unclassified",
    ("positions_designations", "United Kingdom", "INSURANCE EXECUTIVE"): "Executive Management",
    ("positions_designations", "France", "General Manager,Member"): "Executive Management",
    ("positions_designations", "United States", "MANAGER MEMBER"): "Owner / Controller",
    ("positions_designations", "Hungary", "General Manager"): "Other / Unclassified",
    ("positions_designations", "Greece", "Πρόεδρος"): "Executive Management",
    ("positions_designations", "Germany", "Manager,Sole Confidential Clerk / Sole Procurator"): "Authorized Representative",
    ("positions_designations", "France", "Liquidating Agent,Managing Partner"): "Authorized Representative",
    ("positions_designations", "Italy", "ADMINISTRATIVE PARTNER, TECHNICAL MANAGER"): "Owner / Controller",
    ("positions_designations", "Taiwan, Province of China", "General Manager"): "Other / Unclassified",
    ("positions_designations", "Hong Kong", "Director"): "Director",
    ("positions_designations", "Indonesia", "Director,Personnel Director"): "Director",
    ("business_legal_form", "", "Fundação ou Associação Domiciliada no Exterior"): "Non-Profit / Cooperative",
    ("business_legal_form", "", "Sa"): "Company",
    ("business_legal_form", "", "Joint Inheritance Rights"): "Partnership",
    ("business_legal_form", "", "SARL COOPERATIVE CRAISSANAL"): "Company",
    ("psc_beneficiary_type", "", "A"): "Other / Unclassified",
    ("psc_beneficiary_type", "", "Associé en nom"): "Owner / Beneficial Owner",
    ("psc_beneficiary_type", "", "Estimated Shareholding Percentage"): "Owner / Beneficial Owner",
    ("psc_beneficiary_type", "", "Gérant, Associé indéfiniment responsable"): "Owner / Beneficial Owner",
    ("psc_beneficiary_type", "", "Parent"): "Root Business",
    ("psc_beneficiary_type", "", "Cambio de identidad del socio único"): "Owner / Beneficial Owner",
    ("brn_type", "", "AUT NATL BANK NO"): "Business Registration Number",
    ("brn_type", "", "US General Services Administration Unique Entity Identifier"): "Business Registration Number",
    ("brn_type", "", "ALEI"): "Other / Unclassified",
}


class ReviewedOverrideTests(unittest.TestCase):
    def test_all_reviewed_disagreements_resolve_to_user_decision(self) -> None:
        lookups = load_lookup()
        self.assertEqual(27, len(REVIEWED_CASES))
        for (field, country, raw), expected in REVIEWED_CASES.items():
            with self.subTest(field=field, country=country, raw=raw):
                self.assertEqual(expected, lookups[field].get(raw, country))

    def test_country_specific_override_does_not_leak_to_other_countries(self) -> None:
        lookups = load_lookup()
        positions = lookups["positions_designations"]
        self.assertEqual("Other / Unclassified", positions.get("Associate", "Italy"))
        self.assertEqual("Owner / Controller", positions.get("Associate", "Netherlands"))

    def test_lookup_exposes_reviewed_and_historical_provenance(self) -> None:
        positions = load_lookup()["positions_designations"]
        self.assertEqual(
            ("Director", "reviewed_country"),
            positions.get_with_source("Director", "Hong Kong"),
        )
        historical = positions.get_with_source("Director", "Indonesia")
        self.assertIsNotNone(historical)
        self.assertTrue(historical[1].startswith("historical_"))

    def test_reviewed_override_wins_without_entering_similarity_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master.json"
            overrides = root / "overrides.json"
            master.write_text(json.dumps({
                "positions_designations": {
                    "consistent": {},
                    "by_country": {"Italy": {"Associate": "Owner / Controller"}},
                },
            }), encoding="utf-8")
            overrides.write_text(json.dumps({
                "fields": {
                    "positions_designations": {
                        "consistent": {},
                        "by_country": {"Italy": {"Associate": "Other / Unclassified"}},
                    },
                },
            }), encoding="utf-8")

            positions = load_lookup(master, overrides)["positions_designations"]
            self.assertEqual("Other / Unclassified", positions.get("Associate", "Italy"))
            matches = positions.similar("Associate", "Italy", min_score=1.0)
            self.assertEqual("Owner / Controller", matches[0].standardized_value)

    def test_prompts_retain_reviewed_policy_clarifications(self) -> None:
        positions = (ROOT / "prompts" / "positions_designations.md").read_text(
            encoding="utf-8"
        )
        legal_form = (ROOT / "prompts" / "business_legal_form.md").read_text(
            encoding="utf-8"
        )
        beneficiary = (ROOT / "prompts" / "psc_beneficiary_type.md").read_text(
            encoding="utf-8"
        )
        brn = (ROOT / "prompts" / "brn_type.md").read_text(encoding="utf-8")

        self.assertIn('"Chief Executive" without "Officer"', positions)
        self.assertIn("Company Secretary in any jurisdiction", positions)
        self.assertIn('"General Manager,Member" maps to Executive Management', positions)
        self.assertIn("Liquidating Agent", positions)
        self.assertIn('bare "Πρόεδρος" maps to Executive Management', positions)
        self.assertIn('"Joint Inheritance Rights" maps to Partnership', legal_form)
        self.assertIn('Bare "Parent" defaults to Root Business', beneficiary)
        self.assertIn("ALEI does not map to LEI", brn)


if __name__ == "__main__":
    unittest.main()
