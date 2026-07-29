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
Additional output requirements (confidence, alternatives, and reasoning):

For every classified value use one of these three formats depending on confidence:

HIGH — clear, unambiguous match:
  <number>. <Standardized Value> | HIGH

MEDIUM — required judgment, inferred equivalence, or less common synonym.
  Append a one-sentence reasoning explanation:
  <number>. <Standardized Value> | MEDIUM | Reason: <one sentence>

LOW — ambiguous, borderline, or meaningfully uncertain.
  Append ranked alternatives (most to least probable, comma-separated) AND a one-sentence reasoning explanation:
  <number>. <Standardized Value> | LOW | Alternatives: <Alt1>, <Alt2> | Reason: <one sentence>

Examples:
  1. Director | HIGH
  2. Executive Management | MEDIUM | Reason: "Managing Director" is primarily executive but could be Board Member in some jurisdictions
  3. Board Member | LOW | Alternatives: Director, Executive Management | Reason: "Non-Executive" prefix and board meeting context make this ambiguous between Board Member and Director

Rules:
- Alternatives must be drawn only from the canonical values listed in the taxonomy above.
- Alternatives are ranked most probable first.
- Do not add any other text, explanation, or punctuation beyond these formats.
- The final [Total: X of Y mapped] confirmation line is unchanged and still required.
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
    alternatives: list[str] = field(default_factory=list)  # LOW only, ranked most→least probable
    reasoning: str = ""  # MEDIUM and LOW only

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
                "alternatives": r.alternatives,
                "reasoning": r.reasoning,
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
# LOW: "3. Board Member | LOW | Alternatives: Director, Executive Management | Reason: ..."
_OUTPUT_WITH_LOW = re.compile(
    r"^\s*(\d+)[.)]\s*(.+?)\s*\|\s*LOW\s*\|\s*Alternatives:\s*(.+?)\s*\|\s*Reason:\s*(.+?)\s*$",
    re.IGNORECASE,
)
# MEDIUM: "2. Executive Management | MEDIUM | Reason: ..."
_OUTPUT_WITH_MEDIUM = re.compile(
    r"^\s*(\d+)[.)]\s*(.+?)\s*\|\s*MEDIUM\s*\|\s*Reason:\s*(.+?)\s*$",
    re.IGNORECASE,
)
# HIGH with extra trailing content the model sometimes appends (e.g. "| Reason: ...").
# Strip the extra and treat as plain HIGH — the value itself is still valid.
_OUTPUT_WITH_HIGH_EXTRA = re.compile(
    r"^\s*(\d+)[.)]\s*(.+?)\s*\|\s*HIGH\s*\|.+$",
    re.IGNORECASE,
)
_TOTAL_LINE = re.compile(r"\[\s*Total:\s*(\d+)\s+of\s+(\d+)\s+mapped\s*\]", re.IGNORECASE)


def parse_response(text: str, raw_values: list[str]) -> BatchResult:
    """Parse a numbered model response into aligned results.

    Alignment is by the explicit line number the model emits, not by position,
    then cross-checked against expected order. Any gap, duplicate, wrong count,
    or out-of-range index is recorded as a warning rather than silently
    producing a misaligned column.

    Three formats are accepted (most specific tried first):
      LOW:    "<n>. <value> | LOW | Alternatives: <a>, <b> | Reason: <text>"
      MEDIUM: "<n>. <value> | MEDIUM | Reason: <text>"
      HIGH:   "<n>. <value> | HIGH"
    A line with a value but no parseable confidence still counts as answered
    but is flagged via ClassificationResult.needs_review.
    """
    expected = len(raw_values)
    warnings: list[str] = []

    # index -> (value, confidence, alternatives, reasoning)
    parsed: dict[int, tuple[str, str, list[str], str]] = {}

    for line in text.splitlines():
        if _TOTAL_LINE.search(line):
            continue

        # Try LOW with alternatives + reason first (most specific).
        m = _OUTPUT_WITH_LOW.match(line)
        if m:
            idx = int(m.group(1))
            value = m.group(2).strip()
            alternatives = [a.strip() for a in m.group(3).split(",") if a.strip()]
            reasoning = m.group(4).strip()
            if idx in parsed:
                warnings.append(f"duplicate output for item {idx}")
            else:
                parsed[idx] = (value, "LOW", alternatives, reasoning)
            continue

        # Try MEDIUM with reason.
        m = _OUTPUT_WITH_MEDIUM.match(line)
        if m:
            idx = int(m.group(1))
            value = m.group(2).strip()
            reasoning = m.group(3).strip()
            if idx in parsed:
                warnings.append(f"duplicate output for item {idx}")
            else:
                parsed[idx] = (value, "MEDIUM", [], reasoning)
            continue

        # HIGH with extra trailing content — strip and treat as plain HIGH.
        m = _OUTPUT_WITH_HIGH_EXTRA.match(line)
        if m:
            idx = int(m.group(1))
            value = m.group(2).strip()
            if idx in parsed:
                warnings.append(f"duplicate output for item {idx}")
            else:
                parsed[idx] = (value, "HIGH", [], "")
            continue

        # Plain confidence (HIGH, or degraded LOW/MEDIUM without extras).
        m = _OUTPUT_WITH_CONFIDENCE.match(line)
        if m:
            idx = int(m.group(1))
            value = m.group(2).strip()
            confidence = m.group(3).upper()
            if idx in parsed:
                warnings.append(f"duplicate output for item {idx}")
            else:
                parsed[idx] = (value, confidence, [], "")
            continue

        # Numbered line with no confidence tag at all.
        m = _NUMBERED_LINE.match(line)
        if m:
            idx = int(m.group(1))
            value = m.group(2).strip()
            if idx not in parsed:
                warnings.append(f"item {idx}: no confidence tag parsed")
                parsed[idx] = (value, "", [], "")

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
            results.append(ClassificationResult(
                index=i, raw_value=raw, standardized_value="", confidence=""
            ))
        else:
            value, confidence, alternatives, reasoning = entry
            results.append(ClassificationResult(
                index=i, raw_value=raw, standardized_value=value,
                confidence=confidence, alternatives=alternatives, reasoning=reasoning,
            ))

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

        spec = _fields.get(field_key)
        self.field_key = field_key
        self._catch_all = spec.standard_values[-1]
        self._standard_values = spec.standard_values
        self.name = f"MOCK (simulated — no API key used) [{field_key}]"

    def _mock_alternatives(self, exclude: str | None = None) -> list[str]:
        """First 2 non-catch-all standard values (excluding the primary result) as generic alternatives."""
        return [
            v for v in self._standard_values
            if v != self._catch_all and v != exclude
        ][:2]

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
        "pty", "proprietary company", "proprietary limited",
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

    def _classify_one(self, raw: str) -> tuple[str, str, list[str], str]:
        text = " ".join(str(raw).splitlines()).strip()
        country = ""
        m = _COUNTRY_PREFIX.match(text)
        if m:
            country = m.group(1).strip().lower()
            text = text[m.end():]
        t = text.lower()
        if not t:
            return (
                self._catch_all, "LOW",
                self._mock_alternatives(),
                "Empty input — no classification possible",
            )
        if self.field_key == "positions_designations":
            if country in self._UK_STYLE_BOARD_COUNTRIES and any(
                _matches_keyword(t, k) for k in self._UK_STYLE_BOARD_TRIGGERS
            ):
                return "Board Member", "HIGH", [], ""
            value, confidence = self._classify_positions(t)
        elif self.field_key == "business_legal_form":
            value, confidence = self._classify_blf(t)
        else:
            # No heuristic modeled for this field — honest fallback.
            # See class docstring.
            return (
                self._catch_all, "LOW",
                self._mock_alternatives(),
                "No keyword heuristic implemented for this field in simulation — "
                "real Claude would apply the full prompt taxonomy",
            )
        if confidence == "LOW":
            return (
                value, "LOW",
                self._mock_alternatives(exclude=value),
                "No keyword rule matched in simulation — "
                "real Claude would analyse the full taxonomy context",
            )
        return value, confidence, [], ""

    def complete(self, system_prompt: str, user_message: str) -> str:
        # Read back the numbered inputs exactly as a real model would see them.
        inputs: list[tuple[int, str]] = []
        for line in user_message.splitlines():
            m = _NUMBERED_LINE.match(line)
            if m:
                inputs.append((int(m.group(1)), m.group(2)))

        out_lines = []
        for idx, val in inputs:
            value, confidence, alternatives, reasoning = self._classify_one(val)
            if confidence == "LOW":
                alts_str = ", ".join(alternatives)
                out_lines.append(
                    f"{idx}. {value} | LOW | Alternatives: {alts_str} | Reason: {reasoning}"
                )
            elif confidence == "MEDIUM":
                out_lines.append(f"{idx}. {value} | MEDIUM | Reason: {reasoning}")
            else:
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
