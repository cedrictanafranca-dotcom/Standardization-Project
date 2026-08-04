"""Regression tests for universal mapping explanations."""

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
from mapping_reason import build_mapping_reason, build_reviewed_selection_reason
from standardize_file import MAPPING_REASON_COLUMN, standardize_dataframe


class _NoApiClient:
    def create_message(self, *args, **kwargs):
        raise AssertionError("These test values should resolve without an API call")


class MappingReasonTests(unittest.TestCase):
    def test_reviewed_historical_and_model_reasons_include_taxonomy_basis(self) -> None:
        for source in ("reviewed_country", "historical_country", "model"):
            with self.subTest(source=source):
                reason = build_mapping_reason(
                    field_key="positions_designations",
                    raw_value="Director",
                    standardized_value="Director",
                    source=source,
                    country="Hong Kong",
                )
                self.assertIn("role or entity signal", reason)
                self.assertIn("Positions / Designations taxonomy", reason)
                self.assertGreater(len(reason.split()), 12)

    def test_exact_lookup_placeholder_and_blank_all_receive_reasons(self) -> None:
        spec = fields.get("positions_designations")
        df = pd.DataFrame({
            "Country": ["Hong Kong", "Hong Kong", "Hong Kong"],
            "Value": ["Director", "N/A", ""],
        })

        result, _ = standardize_dataframe(
            df,
            column="Value",
            system_prompt=spec.load_prompt(),
            client=_NoApiClient(),
            country_dependent=True,
            country_column="Country",
            field_key=spec.key,
            canonical_values=spec.standard_values,
        )

        self.assertTrue(result[MAPPING_REASON_COLUMN].str.strip().ne("").all())
        self.assertIn("previously confirmed", result.loc[0, MAPPING_REASON_COLUMN])
        self.assertIn("missing-data placeholder", result.loc[1, MAPPING_REASON_COLUMN])
        self.assertIn("No source value was provided", result.loc[2, MAPPING_REASON_COLUMN])

    def test_review_selection_reason_records_confirmation_or_change(self) -> None:
        confirmed = build_reviewed_selection_reason(
            field_key="positions_designations",
            raw_value="Director",
            standardized_value="Director",
            country="Hong Kong",
            previous_value="Director",
            confirmed=True,
        )
        changed = build_reviewed_selection_reason(
            field_key="positions_designations",
            raw_value="Director,Personnel Director",
            standardized_value="Director",
            country="Indonesia",
            previous_value="Other / Unclassified",
        )

        self.assertIn("confirmed", confirmed)
        self.assertIn('changed the classification from "Other / Unclassified"', changed)


if __name__ == "__main__":
    unittest.main()
