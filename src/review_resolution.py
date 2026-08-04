"""Resolve a review-row field label to its canonical field registry entry.

Processing normalizes legacy analytics labels (for example,
``Standardized Position`` becomes ``Universal Position``). The run summary
retains the original label, so review controls must understand both forms.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from analytics_format import resolve_field_type, resolve_standard_field


def resolve_review_field_key(
    field_type: object,
    field_summaries: Iterable[Mapping[str, object]] = (),
    fallback: str | None = None,
) -> str | None:
    """Return the registry key for an original or normalized field label."""
    label = " ".join(str(field_type or "").split())

    for summary in field_summaries:
        summary_label = " ".join(str(summary.get("field_type") or "").split())
        if label == summary_label and summary.get("known") and summary.get("field_key"):
            return str(summary["field_key"])

    if label:
        # Analytics and mixed-field files accept slightly different aliases.
        for resolver in (resolve_field_type, resolve_standard_field):
            resolved = resolver(label)
            if resolved:
                return resolved

    return fallback
