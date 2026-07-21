"""Step 2 — Core classification function (one field, one file).
Step 8 — confidence flagging.

This module owns the *contract* between the app and the model, independent of
whether the model is real or simulated:

  - build_user_message()  turns raw values into the numbered input the prompt
                          expects.
  - CONFIDENCE_ADDENDUM   extends the output contract to require a confidence
                          level per value (HIGH/MEDIUM/LOW), appended to every
                          field's prompt at load time (see fields.py) rather
                          than edited into the verbatim field prompt files.
  - parse_response()      turns the model's numbered "value | CONFIDENCE" text
                          back into an ordered list, and validates count +
                          ordering (the alignment bug the brief warns about —
                          2.5) as well as confidence presence.
  - two interchangeable clients expose the SAME .complete() method:
        MockClaudeClient  — no API key, no network; simulates a response in the
                            exact output format the real model must produce.
        RealClaudeClient  — the real Anthropic call, ready to swap in once an
                            API key is configured (Section 11).
  - classify_values()     orchestrates the above and returns aligned results.

Because both clients return text in the same contract, moving from mock to real
is a one-line change (which client you construct) — nothing else changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")

# Appended to every field's prompt at load time (fields.py FieldSpec.load_prompt)
# — NOT edited into the verbatim per-field prompt files, so the brief's "copy
# verbatim, don't paraphrase" instruction for the core taxonomy rules stays
# honored while still extending the output contract for Step 8.
CONFIDENCE_ADDENDUM = """
Additional output requirement (confidence flagging):
For each classified value, append a confidence level immediately after it on
the SAME numbered line, separated by " | ", in exactly this format:
<number>. <Standardized Value> | <CONFIDENCE>
Where <CONFIDENCE> is exactly one of: HIGH, MEDIUM, LOW.
- HIGH: the input clearly and unambiguously matches one canonical value per the rules above.
- MEDIUM: the input required judgment, an inferred equivalence, or a less common synonym.
- LOW: the input is ambiguous, borderline between two values, or you are meaningfully uncertain.
Example line: 3. Director | HIGH
Do not add any other text, explanation, or punctuation beyond this format.
The final [Total: X of Y mapped] confirmation line is unchanged and still required.
""".strip()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass
class ClassificationResult:
    """One raw value paired with its standardized value, in input order."""

    index: int  # 1-based position in the input batch
    raw_value: str
    standardized_value: str
    confidence: str = ""  # HIGH / MEDIUM / LOW, or "" if not parsed/applicable

    @property
    def needs_review(self) -> bool:
        """LOW confidence, or missing/unparseable confidence, needs a human look."""
        return self.confidence in ("", "LOW")


@dataclass
class BatchResult:
    results: list[ClassificationResult]
    total_reported: int | None  # the "[Total: X of Y mapped]" X, if present
    total_expected: int  # number of inputs we sent
    raw_response: str  # exact text the client returned (for debugging)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.warnings

    def as_rows(self) -> list[dict]:
        return [
            {
                "raw_value": r.raw_value,
                "standardized_value": r.standardized_value,
                "confidence": r.confidence,
            }
            for r in self.results
        ]


# ---------------------------------------------------------------------------
# The contract: input framing + output parsing
# ---------------------------------------------------------------------------
def build_user_message(raw_values: list[str]) -> str:
    """Frame the raw values as the numbered input the system prompt expects.

    Newlines inside a single raw value are collapsed so every entry stays on
    one line — otherwise the numbered output can't be aligned back reliably.
    """
    lines = [f"Classify the following {len(raw_values)} entries:", ""]
    for i, value in enumerate(raw_values, start=1):
        one_line = " ".join(str(value).splitlines()).strip()
        lines.append(f"{i}. {one_line}")
    return "\n".join(lines)


_NUMBERED_LINE = re.compile(r"^\s*(\d+)[.)]\s*(.+?)\s*$")
_OUTPUT_WITH_CONFIDENCE = re.compile(
    r"^\s*(\d+)[.)]\s*(.+?)\s*\|\s*(HIGH|MEDIUM|LOW)\s*$", re.IGNORECASE
)
_TOTAL_LINE = re.compile(r"\[\s*Total:\s*(\d+)\s+of\s+(\d+)\s+mapped\s*\]", re.IGNORECASE)


def parse_response(text: str, raw_values: list[str]) -> BatchResult:
    """Parse a numbered model response into aligned results.

    Alignment is by the explicit line number the model emits, not by position,
    then cross-checked against expected order. Any gap, duplicate, wrong count,
    or out-of-range index is recorded as a warning rather than silently
    producing a misaligned column.

    Each line is expected as "<n>. <value> | <CONFIDENCE>" (Step 8's extended
    contract). A line with a value but no parseable confidence tag still
    counts as answered — the value is kept and confidence is left "" — but is
    flagged via ClassificationResult.needs_review and recorded as a warning,
    since a missing confidence tag is itself a signal something's off.
    """
    expected = len(raw_values)
    warnings: list[str] = []

    # Collect index -> (value, confidence) from every numbered line.
    parsed: dict[int, tuple[str, str]] = {}
    for line in text.splitlines():
        if _TOTAL_LINE.search(line):
            continue  # handled separately below
        m = _OUTPUT_WITH_CONFIDENCE.match(line)
        if m:
            idx = int(m.group(1))
            value = m.group(2).strip()
            confidence = m.group(3).upper()
        else:
            m = _NUMBERED_LINE.match(line)
            if not m:
                continue
            idx = int(m.group(1))
            value = m.group(2).strip()
            confidence = ""
            warnings.append(f"item {idx}: no confidence tag parsed")
        if idx in parsed:
            warnings.append(f"duplicate output for item {idx}")
        parsed[idx] = (value, confidence)

    # Reported total, if the model included the confirmation line.
    total_reported: int | None = None
    tm = _TOTAL_LINE.search(text)
    if tm:
        total_reported = int(tm.group(1))
        reported_of = int(tm.group(2))
        if reported_of != expected:
            warnings.append(
                f"model's [Total: … of {reported_of}] != {expected} inputs sent"
            )

    # Build results in input order, flagging any missing/extra indices.
    results: list[ClassificationResult] = []
    for i, raw in enumerate(raw_values, start=1):
        entry = parsed.get(i)
        if entry is None:
            warnings.append(f"no output returned for item {i}")
            value, confidence = "", ""  # keep alignment; blank marks the gap
        else:
            value, confidence = entry
        results.append(
            ClassificationResult(index=i, raw_value=raw, standardized_value=value, confidence=confidence)
        )

    extra = sorted(k for k in parsed if k < 1 or k > expected)
    if extra:
        warnings.append(f"output had out-of-range item numbers: {extra}")

    if len(parsed) != expected:
        warnings.append(f"parsed {len(parsed)} outputs for {expected} inputs")

    if total_reported is not None and total_reported != len(parsed):
        warnings.append(
            f"model reported {total_reported} mapped but {len(parsed)} lines parsed"
        )

    return BatchResult(
        results=results,
        total_reported=total_reported,
        total_expected=expected,
        raw_response=text,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Clients — both expose .complete(system_prompt, user_message) -> str
# ---------------------------------------------------------------------------
class ClaudeClient(Protocol):
    name: str

    def complete(self, system_prompt: str, user_message: str) -> str: ...


class RealClaudeClient:
    """The real Anthropic call. Ready to use once a key is in .env.

    Not exercised in the mock demo, but kept here so going live is literally
    just constructing this instead of MockClaudeClient.
    """

    name = "REAL (Anthropic API)"

    def __init__(self, model: str | None = None, max_tokens: int = 4096):
        import anthropic  # imported lazily so the mock path needs no key
        import config

        self.client = anthropic.Anthropic(api_key=config.get_api_key())
        self.model = model or config.get_model()
        self.max_tokens = max_tokens

    def complete(self, system_prompt: str, user_message: str) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )


_COUNTRY_PREFIX = re.compile(r"^\[country:\s*(.+?)\]\s*", re.IGNORECASE)


def _matches_keyword(text: str, keyword: str) -> bool:
    """Substring match for multi-word phrases; whole-word match for single
    tokens, so a short abbreviation (e.g. "ag", "lp") can't false-positive
    inside an unrelated word (e.g. "management", "help")."""
    if " " in keyword:
        return keyword in text
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text))


class MockClaudeClient:
    """Simulates the model WITHOUT any API key or network call, for ONE field.

    Parses the numbered input we send and returns text in the *exact* output
    format the real system prompt demands (numbered lines + the
    "[Total: X of Y mapped]" confirmation) — proving the pipeline and output
    contract without touching the real API.

    Only two fields have a real keyword heuristic behind them here — Positions
    / Designations and Business Legal Form, the two the brief calls "most
    refined" (build plan 0.2). Any OTHER field falls back honestly to that
    field's own catch-all value (from the registry in fields.py) for every
    input, rather than pretending to understand a taxonomy it has no rules
    for. That's a mock limitation, not something the real Claude API would do
    — it's why Step 5.4's cross-field proof is about the PIPELINE (registry
    lookup, batching, retry, logging) working for any field, not mock accuracy.
    """

    def __init__(self, field_key: str = "positions_designations"):
        import fields as _fields  # local import avoids a load-time cycle

        self.field_key = field_key
        self._catch_all = _fields.get(field_key).standard_values[-1]
        self.name = f"MOCK (simulated — no API key used) [{field_key}]"

    # --- Positions / Designations: checked in this order, first hit wins.
    # Mirrors the prompt's priority (Board > Director > Exec > Owner > Auth
    # Rep > catch-all), with management/secretary terms special-cased per the
    # category-6 definition.
    _POS_OTHER_OVERRIDES = [
        "company secretary", "operations manager", "general manager",
        "branch manager", "department manager", "program manager",
        "project manager", "regional manager",
    ]
    _POS_BOARD = [
        "chairman", "chairperson", "non-executive director", "non executive director",
        "(ned)", " ned", "supervisory board", "board member", "board chair",
        "commissioner", "aufsichtsrat", "vorstand", "consigliere",
    ]
    _POS_DIRECTOR = ["director", "administrateur", "bestuurder", "amministratore"]
    _POS_EXEC = [
        "chief executive", "ceo", "managing director", "president",
        "chief financial", "cfo", "chief operating", "coo",
        "chief technology", "cto", "vice president", "geschäftsführer",
        "directeur", "treasurer", "controller", "secretary", "officer",
    ]
    _POS_OWNER = [
        "beneficial owner", "ubo", "person with significant control", "psc",
        "shareholder", "co-owner", "owner", "proprietor", "managing partner",
        "general partner", "limited partner", "partner", "managing member",
        "member-manager", "member", "principal", "parent", "vennoot",
    ]
    _POS_AUTHREP = [
        "legal representative", "authorized representative", "authorised representative",
        "chief representative", "authorized signatory", "signatory",
        "power of attorney", "procurator", "registered agent", "process agent",
        "resident agent", "statutory agent", "incorporator", "organizer",
        "liquidator", "receiver", "insolvency", "legal counsel", "general counsel",
        "solicitor", "attorney", "prokurist", "représentant", "reprsentant",
    ]

    def _classify_positions(self, t: str) -> tuple[str, str]:
        # A recognized keyword hit is simulated as HIGH confidence; falling
        # through to the catch-all (no rule matched) is simulated as LOW —
        # a rough stand-in for "the model was sure" vs "the model guessed".
        if any(k in t for k in self._POS_OTHER_OVERRIDES):
            return self._catch_all, "HIGH"
        if any(k in t for k in self._POS_BOARD):
            return "Board Member", "HIGH"
        if any(k in t for k in self._POS_DIRECTOR):
            return "Director", "HIGH"
        if any(k in t for k in self._POS_EXEC):
            return "Executive Management", "HIGH"
        if any(k in t for k in self._POS_OWNER):
            return "Owner / Controller", "HIGH"
        if any(k in t for k in self._POS_AUTHREP):
            return "Authorized Representative", "HIGH"
        return self._catch_all, "LOW"

    # --- Business Legal Form: checked in the prompt's precedence order
    # (Company > Partnership > Sole Prop > Non-Profit > Trust > Foreign >
    # Government > catch-all).
    _BLF_COMPANY = [
        "llc", "gmbh", "ltd", "limited", "plc", "ag", "bv", "nv", "pty ltd",
        "sarl", "sas", "spa", "sociedad limitada", "corp", "corporation",
        "inc", "incorporated", "holding", "unlimited company", "ulc",
        "joint stock company", "private limited",
    ]
    _BLF_PARTNERSHIP = ["partnership", "llp", "lp", "vof", "snc", "ohg", "kg", "joint venture"]
    _BLF_SOLE_PROP = [
        "sole trader", "sole proprietorship", "individual business", "proprietorship",
        "trader", "craftsman", "auto-entrepreneur", "entrepreneur individuel",
    ]
    _BLF_NONPROFIT = [
        "nonprofit", "non-profit", "npo", "association", "foundation",
        "cooperative", "co-op", "credit union", "stichting", "verein",
    ]
    _BLF_TRUST = ["trust", "fund", "scheme"]
    _BLF_FOREIGN = [
        "branch", "establishment", "overseas", "foreign company", "subsidiary",
        "division", "extraprovincial",
    ]
    _BLF_GOV = [
        "government", "municipality", "commune", "public authority",
        "ministry", "statutory body", "state-owned",
    ]

    def _classify_blf(self, t: str) -> tuple[str, str]:
        # Partnership is checked BEFORE Company, ahead of the documented
        # Company > Partnership precedence: that precedence is for entries
        # with two genuinely competing signals (e.g. "LLC / Partnership"),
        # not for legal-form names like "Limited Partnership" / "Limited
        # Liability Partnership" where "Limited" just qualifies the
        # partnership's liability structure. Company's "limited" keyword is
        # too broad to tell those apart, so Partnership goes first — this
        # was a real bug (Step 7 validation): the old order classified both
        # as Company. Tradeoff: a genuinely dual-signal entry like
        # "LLC / Partnership" would now read as Partnership instead of
        # Company: rare in the ground-truth data, so worth it for the more
        # common case.
        if any(_matches_keyword(t, k) for k in self._BLF_PARTNERSHIP):
            return "Partnership", "HIGH"
        if any(_matches_keyword(t, k) for k in self._BLF_COMPANY):
            return "Company", "HIGH"
        if any(_matches_keyword(t, k) for k in self._BLF_SOLE_PROP):
            return "Sole Proprietorship / Individual Business", "HIGH"
        if any(_matches_keyword(t, k) for k in self._BLF_NONPROFIT):
            return "Non-Profit / Cooperative", "HIGH"
        if any(_matches_keyword(t, k) for k in self._BLF_TRUST):
            return "Trust / Fund / Scheme", "HIGH"
        if any(_matches_keyword(t, k) for k in self._BLF_FOREIGN):
            return "Foreign Entity / Branch", "HIGH"
        if any(_matches_keyword(t, k) for k in self._BLF_GOV):
            return "Government / Public Sector Entity", "HIGH"
        return self._catch_all, "LOW"

    # Country context arrives as a "[Country: X] " prefix (see
    # standardize_file.py's country-dependent framing). Only ONE of the
    # Positions prompt's ~30 countries' worth of regional rules is
    # implemented here — the explicit, clean UK/GI/IE/MT Step 4 override
    # ("CEO"/"Managing Director" -> Board Member, not Executive Management) —
    # as a concrete proof that country-aware classification reaches the mock
    # correctly. The other ~58 country-dependent raw values in the ground
    # truth (Section 11 finding) stem from country-specific keyword tables
    # this mock doesn't model; real Claude reads the full prompt and handles
    # all of them. The point here is the PIPELINE now passes country through
    # correctly end to end, not that the mock has full regional coverage.
    _UK_STYLE_BOARD_COUNTRIES = {
        "uk", "united kingdom", "gb", "great britain",
        "gi", "gibraltar", "ie", "ireland", "mt", "malta",
    }
    _UK_STYLE_BOARD_TRIGGERS = ["ceo", "chief executive officer", "chief executive", "managing director"]

    def _classify_one(self, raw: str) -> tuple[str, str]:
        text = " ".join(str(raw).splitlines()).strip()
        country = ""
        m = _COUNTRY_PREFIX.match(text)
        if m:
            country = m.group(1).strip().lower()
            text = text[m.end():]
        t = text.lower()
        if not t:
            return self._catch_all, "LOW"
        if self.field_key == "positions_designations":
            if country in self._UK_STYLE_BOARD_COUNTRIES and any(
                _matches_keyword(t, k) for k in self._UK_STYLE_BOARD_TRIGGERS
            ):
                return "Board Member", "HIGH"
            return self._classify_positions(t)
        if self.field_key == "business_legal_form":
            return self._classify_blf(t)
        # No heuristic modeled for this field yet — honest fallback, not a
        # guess. See the class docstring. Always LOW: the mock has no basis
        # for confidence here.
        return self._catch_all, "LOW"

    def complete(self, system_prompt: str, user_message: str) -> str:
        # Read back the numbered inputs exactly as a real model would see them.
        inputs: list[tuple[int, str]] = []
        for line in user_message.splitlines():
            m = _NUMBERED_LINE.match(line)
            if m:
                inputs.append((int(m.group(1)), m.group(2)))

        out_lines = []
        for idx, val in inputs:
            value, confidence = self._classify_one(val)
            out_lines.append(f"{idx}. {value} | {confidence}")
        out_lines.append(f"[Total: {len(inputs)} of {len(inputs)} mapped]")
        return "\n".join(out_lines)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def classify_values(
    raw_values: list[str],
    system_prompt: str,
    client: ClaudeClient,
) -> BatchResult:
    """Send one batch of raw values through the given client and parse the result."""
    user_message = build_user_message(raw_values)
    response_text = client.complete(system_prompt, user_message)
    return parse_response(response_text, raw_values)
