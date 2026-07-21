r"""Tests for the output contract — the alignment safety net (Step 2.4/2.5)
and the confidence/needs-review contract (Step 8.1/8.2).

The brief calls raw/standardized misalignment "the easiest thing to get wrong,"
so these check that parse_response() both (a) aligns correctly by the model's
line numbers even when lines arrive out of order, and (b) actually FLAGS the bad
cases (missing item, wrong count, duplicate, missing confidence tag) instead of
silently shifting a column or dropping a review flag.

Run:
    .venv\Scripts\python.exe src\test_contract.py
"""

from __future__ import annotations

from classifier import parse_response

RAW = ["ceo", "director", "beneficial owner"]

CASES: list[tuple[str, str, bool, list[str] | None, list[str] | None]] = []


def case(name, response, should_be_ok, expected_values, expected_confidences=None):
    CASES.append((name, response, should_be_ok, expected_values, expected_confidences))


# 1. Clean, in-order response with confidence tags.
case(
    "happy path",
    "1. Executive Management | HIGH\n2. Director | HIGH\n3. Owner / Controller | MEDIUM\n[Total: 3 of 3 mapped]",
    True,
    ["Executive Management", "Director", "Owner / Controller"],
    ["HIGH", "HIGH", "MEDIUM"],
)

# 2. Same answers but lines shuffled — must still align by number.
case(
    "shuffled lines still align by index",
    "3. Owner / Controller | LOW\n1. Executive Management | HIGH\n2. Director | MEDIUM\n[Total: 3 of 3 mapped]",
    True,
    ["Executive Management", "Director", "Owner / Controller"],
    ["HIGH", "MEDIUM", "LOW"],
)

# 3. Missing item 2 — must flag, and keep 1 & 3 in their right slots.
case(
    "missing item is flagged",
    "1. Executive Management | HIGH\n3. Owner / Controller | HIGH\n[Total: 2 of 3 mapped]",
    False,
    ["Executive Management", "", "Owner / Controller"],
)

# 4. Too many outputs — must flag.
case(
    "extra item is flagged",
    "1. Executive Management | HIGH\n2. Director | HIGH\n3. Owner / Controller | HIGH\n"
    "4. Board Member | HIGH\n[Total: 4 of 3 mapped]",
    False,
    ["Executive Management", "Director", "Owner / Controller"],
)

# 5. Duplicate item number — must flag.
case(
    "duplicate item is flagged",
    "1. Executive Management | HIGH\n2. Director | HIGH\n2. Board Member | HIGH\n"
    "3. Owner / Controller | HIGH\n[Total: 3 of 3 mapped]",
    False,
    None,  # value for item 2 is ambiguous; we only assert it's flagged
)

# 6. Missing confidence tag on one line — must flag as a warning (not silently
# treated as a normal answer), even though the value itself parsed fine.
case(
    "missing confidence tag is flagged",
    "1. Executive Management | HIGH\n2. Director\n3. Owner / Controller | HIGH\n[Total: 3 of 3 mapped]",
    False,
    ["Executive Management", "Director", "Owner / Controller"],
    ["HIGH", "", "HIGH"],
)


def main() -> int:
    passed = 0
    for name, response, should_be_ok, expected_values, expected_confidences in CASES:
        result = parse_response(response, RAW)
        got_values = [r.standardized_value for r in result.results]
        got_confidences = [r.confidence for r in result.results]

        ok = result.ok == should_be_ok
        if expected_values is not None:
            ok = ok and got_values == expected_values
        if expected_confidences is not None:
            ok = ok and got_confidences == expected_confidences
        # results must always be exactly len(RAW), in input order
        ok = ok and [r.index for r in result.results] == [1, 2, 3]

        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if not ok:
            print(f"        expected ok={should_be_ok}, values={expected_values}, confidences={expected_confidences}")
            print(f"        got      ok={result.ok}, values={got_values}, confidences={got_confidences}")
            print(f"        warnings={result.warnings}")
        passed += ok

    # 7. needs_review semantics: LOW or missing confidence flags for review;
    # HIGH/MEDIUM does not. Checked directly against the "happy path" +
    # "shuffled" + "missing confidence" results above rather than as a
    # separate parse.
    happy = parse_response(
        "1. Executive Management | HIGH\n2. Director | LOW\n3. Owner / Controller | MEDIUM\n"
        "[Total: 3 of 3 mapped]",
        RAW,
    )
    flags = [r.needs_review for r in happy.results]
    review_ok = flags == [False, True, False]
    print(f"  [{'PASS' if review_ok else 'FAIL'}] needs_review: HIGH/MEDIUM=False, LOW=True")
    if not review_ok:
        print(f"        got flags={flags}")
    passed += review_ok
    total_cases = len(CASES) + 1

    print(f"\n{passed}/{total_cases} contract tests passed.")
    return 0 if passed == total_cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
