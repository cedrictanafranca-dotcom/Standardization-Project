"""Regression tests for normalized field labels in the flagged-review UI."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from review_resolution import resolve_review_field_key


class ReviewResolutionTests(unittest.TestCase):
    def test_normalized_analytics_label_resolves_when_summary_uses_legacy_label(self) -> None:
        summaries = [{
            "field_type": "Standardized Position",
            "field_key": "positions_designations",
            "known": True,
        }]

        self.assertEqual(
            resolve_review_field_key("Universal Position", summaries),
            "positions_designations",
        )

    def test_exact_summary_label_still_resolves(self) -> None:
        summaries = [{
            "field_type": "Standardized Designation",
            "field_key": "positions_designations",
            "known": True,
        }]

        self.assertEqual(
            resolve_review_field_key("Standardized Designation", summaries),
            "positions_designations",
        )


if __name__ == "__main__":
    unittest.main()
