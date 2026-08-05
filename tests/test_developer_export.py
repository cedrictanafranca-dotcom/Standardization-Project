"""Developer script export formatting and safety checks."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import fields
from developer_export import (
    SCRIPT_TEMPLATES,
    build_developer_export,
    country_enum_code,
    ready_script_text,
)
from standardize_file import NEEDS_REVIEW_COLUMN, STANDARDIZED_COLUMN


class DeveloperExportTests(unittest.TestCase):
    def test_formats_example_template_and_removes_duplicates(self) -> None:
        source = pd.DataFrame([
            {
                "Country": "Brazil",
                "Raw": "Empresa",
                STANDARDIZED_COLUMN: "Business",
                NEEDS_REVIEW_COLUMN: "",
            },
            {
                "Country": "Brazil",
                "Raw": "Empresa",
                STANDARDIZED_COLUMN: "Business",
                NEEDS_REVIEW_COLUMN: "",
            },
        ])

        result = build_developer_export(
            source,
            raw_col="Raw",
            country_col="Country",
            fixed_field_key="business_entity_type",
        )

        self.assertEqual(1, len(result))
        self.assertTrue(result.iloc[0]["Status"].startswith("Ready"))
        self.assertEqual("CountryEnum.BR", result.iloc[0]["Country Enum"])
        self.assertEqual(
            "new BusinessTypeStandardization(CountryEnum.BR,~Business~,~Empresa~),",
            ready_script_text(result),
        )

    def test_unconfirmed_review_is_not_emitted(self) -> None:
        source = pd.DataFrame([{
            "Country": "BR",
            "Raw": "Sócio-Administrador",
            STANDARDIZED_COLUMN: "Owner / Controller",
            NEEDS_REVIEW_COLUMN: NEEDS_REVIEW_COLUMN,
        }])

        result = build_developer_export(
            source,
            raw_col="Raw",
            country_col="Country",
            fixed_field_key="business_entity_type",
        )

        self.assertEqual("Excluded: review not confirmed", result.iloc[0]["Status"])
        self.assertEqual("", ready_script_text(result))

    def test_every_supported_field_has_a_provisional_demo_template(self) -> None:
        self.assertEqual(set(fields.FIELDS), set(SCRIPT_TEMPLATES))
        for field_key, spec in fields.FIELDS.items():
            source = pd.DataFrame([{
                "Country": "Brazil",
                "Raw": f"Example {field_key}",
                STANDARDIZED_COLUMN: spec.standard_values[0],
                NEEDS_REVIEW_COLUMN: "",
            }])
            result = build_developer_export(
                source,
                raw_col="Raw",
                country_col="Country",
                fixed_field_key=field_key,
            )
            with self.subTest(field=field_key):
                self.assertTrue(result.iloc[0]["Status"].startswith("Ready"))
                self.assertIn("provisional", result.iloc[0]["Status"].lower())
                self.assertTrue(result.iloc[0]["Generated Script"].startswith("new "))
                self.assertIn("CountryEnum.BR", result.iloc[0]["Generated Script"])

    def test_unknown_country_and_delimiter_are_safe(self) -> None:
        self.assertIsNone(country_enum_code("Unconfirmed Jurisdiction"))

        source = pd.DataFrame([{
            "Country": "Brazil",
            "Raw": "Value ~ needs escaping",
            STANDARDIZED_COLUMN: "Business",
            NEEDS_REVIEW_COLUMN: "",
        }])
        result = build_developer_export(
            source,
            raw_col="Raw",
            country_col="Country",
            fixed_field_key="business_entity_type",
        )
        self.assertIn("delimiter", result.iloc[0]["Status"])
        self.assertEqual("", result.iloc[0]["Generated Script"])


if __name__ == "__main__":
    unittest.main()
