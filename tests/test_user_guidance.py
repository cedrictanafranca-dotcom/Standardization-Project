"""Keep user-facing help synchronized with the active field registry."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import fields
from user_guidance import (
    CLASSIFICATION_RULES,
    FIELD_GUIDANCE,
    parse_country_rules,
    validate_guidance,
)


class UserGuidanceTests(unittest.TestCase):
    def test_every_active_field_and_category_has_guidance(self) -> None:
        specs = fields.list_fields()
        self.assertEqual([], validate_guidance(specs))
        self.assertEqual({spec.key for spec in specs}, set(FIELD_GUIDANCE))
        self.assertEqual({spec.key for spec in specs}, set(CLASSIFICATION_RULES))

    def test_each_definition_is_short_and_has_examples(self) -> None:
        for field_key, guidance in FIELD_GUIDANCE.items():
            with self.subTest(field=field_key):
                self.assertTrue(guidance["summary"].strip())
            for category, detail in guidance["categories"].items():
                with self.subTest(field=field_key, category=category):
                    self.assertTrue(detail["meaning"].strip())
                    self.assertLessEqual(len(detail["meaning"].split()), 30)
                    self.assertTrue(detail["examples"])

    def test_help_pages_exist_in_expected_order(self) -> None:
        self.assertTrue((ROOT / "standardize_page.py").exists())
        self.assertTrue((ROOT / "pages" / "1_Help_and_Field_Guide.py").exists())
        self.assertTrue((ROOT / "pages" / "2_Review_Corrections.py").exists())
        self.assertFalse((ROOT / "pages" / "1_How_To_Use.py").exists())
        self.assertFalse((ROOT / "pages" / "2_Field_Definitions.py").exists())
        self.assertFalse((ROOT / "pages" / "3_Classification_Rules.py").exists())

    def test_shared_brand_theme_and_wordmark_exist(self) -> None:
        self.assertTrue((SRC / "ui_theme.py").exists())
        self.assertTrue((ROOT / "assets" / "trulioo_wordmark_lite_green.png").exists())
        self.assertTrue((ROOT / "assets" / "trulioo_wordmark_sidebar.png").exists())
        from ui_theme import BRAND_CSS
        self.assertIn('font-family: "Material Symbols Rounded" !important', BRAND_CSS)
        self.assertNotIn('html, body, [class*="st-"]', BRAND_CSS)

    def test_active_country_rule_table_can_be_displayed(self) -> None:
        spec = fields.get("positions_designations")
        rules = parse_country_rules(spec.prompt_path.read_text(encoding="utf-8"))
        countries = {rule["country"] for rule in rules}
        self.assertGreaterEqual(len(rules), 30)
        self.assertIn("United Kingdom", countries)
        self.assertIn("Germany", countries)


if __name__ == "__main__":
    unittest.main()
