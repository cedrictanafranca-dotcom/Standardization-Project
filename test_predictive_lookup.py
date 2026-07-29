"""Regression checks for predictive lookup and retrieval-assisted classification."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from classifier import MockClaudeClient, build_user_message, classify_values
from master_lookup import FieldLookup
import standardize_file as sf


class ExampleAwareStub:
    """Deterministic stand-in proving retrieved examples reach the API prompt."""

    name = "EXAMPLE-AWARE TEST STUB"

    def __init__(self) -> None:
        self.last_message = ""

    def complete(self, system_prompt: str, user_message: str) -> str:
        self.last_message = user_message
        assert "Approved historical mappings for context" in user_message
        return "1. Executive Management | HIGH\n[Total: 1 of 1 mapped]"


def test_case_and_punctuation_prediction() -> None:
    lookup = FieldLookup(
        field_key="positions_designations",
        consistent={
            "Managing Director": "Executive Management",
            "Managing Partner": "Owner / Controller",
            "Board Member": "Board Member",
        },
    )

    prediction = lookup.predict_similar("MANAGING DIRECTOR")
    assert prediction is not None
    assert prediction.standardized_value == "Executive Management"
    assert prediction.score == 1.0

    punctuation = lookup.predict_similar("Managing-Director")
    assert punctuation is not None
    assert punctuation.standardized_value == "Executive Management"


def test_country_specific_examples_override_global() -> None:
    lookup = FieldLookup(
        field_key="positions_designations",
        consistent={"CEO": "Executive Management"},
        by_country={"United Kingdom": {"CEO": "Board Member"}},
    )

    uk_prediction = lookup.predict_similar("ceo", "United Kingdom")
    global_prediction = lookup.predict_similar("ceo")
    assert uk_prediction is not None
    assert uk_prediction.standardized_value == "Board Member"
    assert global_prediction is not None
    assert global_prediction.standardized_value == "Executive Management"


def test_ambiguous_neighbors_are_not_auto_predicted() -> None:
    lookup = FieldLookup(
        field_key="positions_designations",
        consistent={
            "Managing Director": "Executive Management",
            "Managing Partner": "Owner / Controller",
        },
    )

    assert lookup.predict_similar("Managing") is None
    matches = lookup.similar("Managing", min_score=0.30)
    assert {m.standardized_value for m in matches} == {
        "Executive Management",
        "Owner / Controller",
    }


def test_examples_are_prompt_context_not_extra_inputs() -> None:
    examples = [[("Managing Director", "Executive Management", 0.82)]]
    message = build_user_message(["Managing Dir"], examples)
    assert "Approved historical mappings for context" in message
    assert "'Managing Director' => 'Executive Management'" in message

    stub = ExampleAwareStub()
    batch = classify_values(
        ["Managing Dir"],
        "test prompt",
        stub,
        examples,
    )
    assert len(batch.results) == 1
    assert batch.results[0].standardized_value == "Executive Management"


def test_pipeline_counts_prediction_and_retrieval() -> None:
    lookup = FieldLookup(
        field_key="positions_designations",
        consistent={
            "Managing Director": "Executive Management",
            "Board Member": "Board Member",
        },
    )
    original = sf._MASTER_LOOKUP
    sf._MASTER_LOOKUP = {"positions_designations": lookup}
    try:
        predicted_df, predicted_stats = sf.standardize_dataframe(
            pd.DataFrame({"Value": ["MANAGING DIRECTOR"]}),
            "Value",
            "test prompt",
            MockClaudeClient("positions_designations"),
            field_key="positions_designations",
            canonical_values=[
                "Board Member",
                "Director",
                "Executive Management",
                "Owner / Controller",
                "Authorized Representative",
                "Other / Unclassified",
            ],
        )
        assert predicted_df.loc[0, sf.STANDARDIZED_COLUMN] == "Executive Management"
        assert predicted_stats.similarity_predictions == 1
        assert predicted_stats.batches == 0

        stub = ExampleAwareStub()
        assisted_df, assisted_stats = sf.standardize_dataframe(
            pd.DataFrame({"Value": ["Managing Dir"]}),
            "Value",
            "test prompt",
            stub,
            field_key="positions_designations",
            canonical_values=[
                "Board Member",
                "Director",
                "Executive Management",
                "Owner / Controller",
                "Authorized Representative",
                "Other / Unclassified",
            ],
        )
        assert assisted_df.loc[0, sf.STANDARDIZED_COLUMN] == "Executive Management"
        assert assisted_stats.retrieval_assisted == 1
        assert assisted_stats.batches == 1
    finally:
        sf._MASTER_LOOKUP = original


def test_placeholders_are_filtered_before_similarity() -> None:
    lookup = FieldLookup(
        field_key="business_legal_form",
        consistent={"NA Holdings": "Company"},
    )
    original = sf._MASTER_LOOKUP
    sf._MASTER_LOOKUP = {"business_legal_form": lookup}
    try:
        result, stats = sf.standardize_dataframe(
            pd.DataFrame({"Value": ["N/A"]}),
            "Value",
            "test prompt",
            ExampleAwareStub(),
            field_key="business_legal_form",
            canonical_values=[
                "Company",
                "Other / Unclassified",
            ],
        )
        assert result.loc[0, sf.STANDARDIZED_COLUMN] == "Other / Unclassified"
        assert stats.similarity_predictions == 0
        assert stats.retrieval_assisted == 0
        assert stats.batches == 0
    finally:
        sf._MASTER_LOOKUP = original


if __name__ == "__main__":
    test_case_and_punctuation_prediction()
    test_country_specific_examples_override_global()
    test_ambiguous_neighbors_are_not_auto_predicted()
    test_examples_are_prompt_context_not_extra_inputs()
    test_pipeline_counts_prediction_and_retrieval()
    test_placeholders_are_filtered_before_similarity()
    print("Predictive lookup tests: 6/6 passed.")
