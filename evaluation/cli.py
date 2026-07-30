"""Command-line entry point for dataset generation, scoring, and comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dataset import build_dataset, load_jsonl
from .metrics import score_predictions
from .models import Prediction
from .automation import calibrate_automation


def _load_predictions(path: Path) -> list[Prediction]:
    return [
        Prediction.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_json(path: Path | None, value: dict | list, *, echo: bool = True) -> None:
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    if echo:
        print(text)


def _build(args: argparse.Namespace) -> int:
    manifest = build_dataset(
        args.lookup,
        args.output_dir,
        test_fraction=args.test_fraction,
        seed=args.seed,
        family_threshold=args.family_threshold,
    )
    _write_json(None, manifest)
    return 0


def _score(args: argparse.Namespace) -> int:
    report = score_predictions(
        load_jsonl(args.dataset),
        _load_predictions(args.predictions),
        args.approach,
    )
    _write_json(args.output, report)
    return 0


def _compare(args: argparse.Namespace) -> int:
    reports = [
        json.loads(path.read_text(encoding="utf-8")) for path in args.reports
    ]
    summary = sorted(
        ({
            "approach": report["approach"],
            "overall_accuracy": report["overall_accuracy"],
            "incorrect_high": report["incorrect_high"]["count"],
            "catch_all_rate": report["catch_all_rate"],
            "review_rate": report["review_rate"],
            "predictive_coverage": report["predictive_coverage"],
            "api_bound_values": report["api_bound_values"]["count"],
        } for report in reports),
        key=lambda row: (-row["overall_accuracy"], row["approach"]),
    )
    _write_json(args.output, summary)
    return 0


def _calibrate(args: argparse.Namespace) -> int:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    policy, report, ambiguities = calibrate_automation(
        load_jsonl(args.dataset),
        args.reference,
        source_lookup_sha256=str(manifest.get("source_sha256", "")),
        target_precision=args.target_precision,
        split_seed=args.split_seed,
    )
    _write_json(args.policy_output, policy.to_dict(), echo=False)
    _write_json(args.report_output, report, echo=False)
    _write_json(args.ambiguity_output, ambiguities, echo=False)
    print(json.dumps({
        "policy_output": str(args.policy_output),
        "report_output": str(args.report_output),
        "ambiguity_output": str(args.ambiguity_output),
        "validation_policy": report["validation_policy"],
    }, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(required=True)

    build = subparsers.add_parser("build", help="create a leakage-free holdout")
    build.add_argument("--lookup", type=Path, default=Path("data/master_lookup.json"))
    build.add_argument("--output-dir", type=Path, default=Path("output/evaluation"))
    build.add_argument("--test-fraction", type=float, default=0.20)
    build.add_argument("--seed", type=int, default=20260729)
    build.add_argument("--family-threshold", type=float, default=0.88)
    build.set_defaults(handler=_build)

    score = subparsers.add_parser("score", help="score one approach's JSONL predictions")
    score.add_argument("--dataset", type=Path, required=True)
    score.add_argument("--predictions", type=Path, required=True)
    score.add_argument("--approach", required=True)
    score.add_argument("--output", type=Path)
    score.set_defaults(handler=_score)

    compare = subparsers.add_parser("compare", help="compare score-report JSON files")
    compare.add_argument("reports", nargs="+", type=Path)
    compare.add_argument("--output", type=Path)
    compare.set_defaults(handler=_compare)

    calibrate = subparsers.add_parser(
        "calibrate",
        help="calibrate deterministic automation thresholds without API calls",
    )
    calibrate.add_argument("--dataset", type=Path, required=True)
    calibrate.add_argument("--reference", type=Path, required=True)
    calibrate.add_argument("--manifest", type=Path, required=True)
    calibrate.add_argument("--target-precision", type=float, default=0.92)
    calibrate.add_argument("--split-seed", type=int, default=20260730)
    calibrate.add_argument("--policy-output", type=Path, required=True)
    calibrate.add_argument("--report-output", type=Path, required=True)
    calibrate.add_argument("--ambiguity-output", type=Path, required=True)
    calibrate.set_defaults(handler=_calibrate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
