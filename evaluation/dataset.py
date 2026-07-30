"""Build a deterministic, leakage-free holdout from master_lookup.json."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .families import DEFAULT_FAMILY_THRESHOLD, build_family_map
from .models import EvaluationRecord

CATCH_ALL = "Other / Unclassified"
SCHEMA_VERSION = 1


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:20]


def load_authoritative_records(lookup_path: Path) -> tuple[list[EvaluationRecord], dict]:
    """Expand the final lookup without changing its country-override semantics."""
    raw_bytes = lookup_path.read_bytes()
    lookup = json.loads(raw_bytes.decode("utf-8"))
    records: list[EvaluationRecord] = []
    seen: set[tuple[str, str, str]] = set()

    for field, field_data in sorted(lookup.items()):
        for raw_value, expected_value in sorted(field_data.get("consistent", {}).items()):
            key = (field, "", raw_value)
            if key in seen:
                raise ValueError(f"duplicate mapping: {key}")
            seen.add(key)
            records.append(EvaluationRecord(
                record_id=_stable_id(*key),
                field=field,
                raw_value=raw_value,
                expected_value=expected_value,
            ))
        for country, country_map in sorted(field_data.get("by_country", {}).items()):
            for raw_value, expected_value in sorted(country_map.items()):
                key = (field, country, raw_value)
                if key in seen:
                    raise ValueError(f"duplicate mapping: {key}")
                seen.add(key)
                records.append(EvaluationRecord(
                    record_id=_stable_id(*key),
                    field=field,
                    country=country,
                    raw_value=raw_value,
                    expected_value=expected_value,
                ))

    metadata = {
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "source_records": len(records),
        "source_fields": len(lookup),
    }
    return records, metadata


def annotate_families(
    records: list[EvaluationRecord],
    threshold: float = DEFAULT_FAMILY_THRESHOLD,
) -> list[EvaluationRecord]:
    family_map = build_family_map(records, threshold)
    family_records: dict[str, list[EvaluationRecord]] = defaultdict(list)
    for record in records:
        family_records[family_map[(record.field, record.raw_value)]].append(record)

    annotated: list[EvaluationRecord] = []
    for record in records:
        family_id = family_map[(record.field, record.raw_value)]
        members = family_records[family_id]
        labels = {member.expected_value for member in members}
        # The flattened lookup has no original occurrence counts. Family
        # support is therefore the explicit common/rare proxy.
        frequency_band = "common" if len(members) >= 2 else "rare"
        annotated.append(replace(
            record,
            family_id=family_id,
            frequency_band=frequency_band,
            ambiguous=len(labels) > 1,
        ))
    return annotated


def _strata(records: list[EvaluationRecord]) -> set[str]:
    values: set[str] = set()
    for record in records:
        country = record.country or "[GLOBAL]"
        values.update({
            f"field:{record.field}",
            f"category:{record.field}:{record.expected_value}",
            f"country:{country}",
            f"frequency:{record.frequency_band}",
            f"ambiguous:{str(record.ambiguous).lower()}",
        })
    return values


def split_by_family(
    records: list[EvaluationRecord],
    test_fraction: float = 0.20,
    seed: int = 20260729,
) -> tuple[list[EvaluationRecord], list[EvaluationRecord], dict[str, Any]]:
    """Greedily stratify whole families across field/category/country strata."""
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test fraction must be in (0, 1)")
    by_family: dict[str, list[EvaluationRecord]] = defaultdict(list)
    for record in records:
        if not record.family_id:
            raise ValueError("records must be family-annotated before splitting")
        by_family[record.family_id].append(record)
    if len(by_family) < 2:
        raise ValueError("at least two value families are required")

    family_strata = {family: _strata(members) for family, members in by_family.items()}
    stratum_totals = Counter(
        stratum for strata in family_strata.values() for stratum in strata
    )
    stratum_targets = {
        stratum: (
            max(1, min(total - 1, round(total * test_fraction)))
            if total >= 2 else 0
        )
        for stratum, total in stratum_totals.items()
    }
    target_records = max(1, min(len(records) - 1, round(len(records) * test_fraction)))
    rng = random.Random(seed)
    tie_breakers = {family: rng.random() for family in sorted(by_family)}
    selected: set[str] = set()
    selected_strata: Counter[str] = Counter()
    selected_records = 0

    while selected_records < target_records and len(selected) < len(by_family) - 1:
        candidates = []
        for family, members in by_family.items():
            if family in selected:
                continue
            unmet_score = sum(
                max(stratum_targets[stratum] - selected_strata[stratum], 0)
                / max(stratum_totals[stratum], 1)
                for stratum in family_strata[family]
            )
            overshoot = abs(target_records - (selected_records + len(members)))
            candidates.append((
                -unmet_score,
                overshoot,
                tie_breakers[family],
                family,
            ))
        if not candidates:
            break
        chosen = min(candidates)[-1]
        selected.add(chosen)
        selected_records += len(by_family[chosen])
        selected_strata.update(family_strata[chosen])

    test = [record for record in records if record.family_id in selected]
    reference = [record for record in records if record.family_id not in selected]
    overlap = {record.family_id for record in test} & {
        record.family_id for record in reference
    }
    if overlap:
        raise AssertionError(f"family leakage detected: {sorted(overlap)[:5]}")

    coverage = {
        "reference_records": len(reference),
        "test_records": len(test),
        "reference_families": len({record.family_id for record in reference}),
        "test_families": len({record.family_id for record in test}),
        "test_fraction_actual": len(test) / len(records),
        "family_overlap": 0,
        "test_by_field": dict(sorted(Counter(r.field for r in test).items())),
        "test_by_category": dict(sorted(
            Counter(f"{r.field}::{r.expected_value}" for r in test).items()
        )),
        "test_by_country": dict(sorted(
            Counter(r.country or "[GLOBAL]" for r in test).items()
        )),
        "test_by_frequency": dict(sorted(Counter(r.frequency_band for r in test).items())),
        "test_ambiguous": sum(record.ambiguous for record in test),
    }
    return reference, test, coverage


def reference_lookup(records: Iterable[EvaluationRecord]) -> dict[str, Any]:
    lookup: dict[str, dict[str, Any]] = {}
    for record in records:
        field_data = lookup.setdefault(
            record.field, {"consistent": {}, "by_country": {}}
        )
        if record.country:
            field_data["by_country"].setdefault(record.country, {})[
                record.raw_value
            ] = record.expected_value
        else:
            field_data["consistent"][record.raw_value] = record.expected_value
    return lookup


def write_jsonl(path: Path, records: Iterable[EvaluationRecord]) -> None:
    path.write_text(
        "".join(
            json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def build_dataset(
    lookup_path: Path,
    output_dir: Path,
    test_fraction: float = 0.20,
    seed: int = 20260729,
    family_threshold: float = DEFAULT_FAMILY_THRESHOLD,
) -> dict[str, Any]:
    records, source_metadata = load_authoritative_records(lookup_path)
    annotated = annotate_families(records, family_threshold)
    reference, test, coverage = split_by_family(annotated, test_fraction, seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    write_jsonl(output_dir / "heldout.jsonl", sorted(test, key=lambda r: r.record_id))
    (output_dir / "reference_lookup.json").write_text(
        json.dumps(reference_lookup(reference), indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "test_fraction_requested": test_fraction,
        "family_threshold": family_threshold,
        "frequency_definition": (
            "common = normalized family has 2+ authoritative mapping records; "
            "rare = singleton. The flattened lookup does not retain source row frequency."
        ),
        **source_metadata,
        **coverage,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def load_jsonl(path: Path) -> list[EvaluationRecord]:
    return [
        EvaluationRecord.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
