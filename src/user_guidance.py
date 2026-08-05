"""Plain-language help content derived from the active classifier taxonomies.

The canonical category names still come from ``fields.py``.  This module adds
short user-facing descriptions and examples without exposing the full prompts.
Tests require every configured category to have guidance so the help page
cannot silently fall behind the classifier.
"""

from __future__ import annotations

import re

GUIDANCE_LAST_UPDATED = "August 4, 2026"


def _item(meaning: str, *examples: str) -> dict:
    return {"meaning": meaning, "examples": list(examples)}


_ENTITY_TYPE = {
    "Individual": _item(
        "A real person rather than a company or other organization.",
        "Individual", "Natural person", "Named director",
    ),
    "Business": _item(
        "A company, organization, trust, partnership, or other legal entity.",
        "Company", "Corporation", "Corporate trustee",
    ),
    "Other / Unclassified": _item(
        "The value is missing, unclear, or does not reliably identify a person or business.",
        "Unknown", "Not specified", "Blank value",
    ),
}

_BUSINESS_STATUS = {
    "Active": _item(
        "The organization is currently registered or legally operating.",
        "Active", "Registered", "In good standing",
    ),
    "Inactive": _item(
        "The organization is no longer active on the official register.",
        "Dissolved", "Deregistered", "Struck off",
    ),
    "Pending / Insolvency": _item(
        "A closure, insolvency, liquidation, or similar legal process has started but is not final.",
        "In administration", "Liquidation pending", "Proposal to strike off",
    ),
    "Other / Unclassified": _item(
        "The status is missing, unclear, or is not a valid legal status.",
        "Unknown", "Not provided", "Blank value",
    ),
}


_ENTITY_TYPE_RULES = {
    "steps": [
        "Choose Individual when the value clearly describes a real person.",
        "Choose Business when it clearly describes a company, organization, or other legal entity.",
        "Use Other / Unclassified when the value is blank, unclear, or does not establish either type.",
    ],
    "priority": "Clear evidence of a person or business wins; uncertain values remain Other / Unclassified.",
}

_BUSINESS_STATUS_RULES = {
    "steps": [
        "Use Active when the organization currently exists on the official register.",
        "Use Inactive when closure, dissolution, or removal is complete.",
        "Use Pending / Insolvency when a closure, restructuring, or insolvency process has started but is not final.",
        "Use Other / Unclassified when the source does not communicate a reliable legal status.",
    ],
    "priority": "Inactive > Pending / Insolvency > Active > Other / Unclassified.",
}


# Plain-language decision summaries. The detailed prompts remain protected and
# version-controlled; this content tells users how those instructions operate
# without turning the application into a prompt editor.
CLASSIFICATION_RULES: dict[str, dict] = {
    "business_legal_form": {
        "steps": [
            "Identify the entity's functional legal structure, including equivalent local-language terms.",
            "Treat an incorporated limited or unlimited entity as a Company.",
            "Use Foreign Entity / Branch for a branch or foreign extension unless a higher-priority legal form is explicit.",
            "Use Other / Unclassified when the legal form cannot be established reliably.",
        ],
        "priority": (
            "Company > Partnership > Sole Proprietorship / Individual Business > "
            "Non-Profit / Cooperative > Trust / Fund / Scheme > Foreign Entity / Branch > "
            "Government / Public Sector Entity > Other / Unclassified."
        ),
        "notes": [
            "An explicitly foreign foundation or association remains Non-Profit / Cooperative.",
            "An incorporated joint venture maps to Company; an unincorporated joint venture can map to Partnership.",
        ],
    },
    "positions_designations": {
        "steps": [
            "Apply the country-specific board and management rules first when country is available.",
            "Use Director for a formally registered director role that is not already resolved as Board Member by a country rule.",
            "Use Executive Management for senior executive authority; ordinary operational manager titles remain Other / Unclassified unless another rule applies.",
            "Use Owner / Controller for clear ownership or control and Authorized Representative for legal signing or representation authority.",
            "Use Other / Unclassified when the title does not establish a supported role.",
        ],
        "priority": "Board Member > Director > Executive Management > Owner / Controller > Authorized Representative > Other / Unclassified.",
        "notes": [
            "A country rule overrides a general keyword rule.",
            "Liquidator, receiver, and insolvency-practitioner authority maps to Authorized Representative and should be reviewed.",
            "Company Secretary maps to Other / Unclassified unless the same entry contains a higher-priority role.",
        ],
    },
    "business_status": _BUSINESS_STATUS_RULES,
    "psc_beneficiary_type": {
        "steps": [
            "Use Root Business for the entity itself or a parent/root entity record.",
            "Use Owner / Beneficial Owner when an ownership interest is established.",
            "Use Controller when control or representation is established without clear ownership.",
            "Use Other / Unclassified for unclear or unsupported relationships.",
        ],
        "priority": "Root Business > Owner / Beneficial Owner > Controller > Other / Unclassified.",
        "notes": [
            "A bare Parent value defaults to Root Business unless the input clearly describes a family relationship.",
        ],
    },
    "brn_type": {
        "steps": [
            "Classify the identifier by who issued it and what it is used for.",
            "Separate business-registration identifiers from tax, VAT, charity, and ISO 17442 LEI identifiers.",
            "Use Proprietary / Third-party ID for a commercial or industry identifier rather than a government identifier.",
            "Use Other / Unclassified for statuses, bank identifiers, procurement codes, unclear labels, or unsupported identifiers.",
        ],
        "priority": "Use the most specific supported identifier purpose shown by the source value.",
        "notes": [
            "GST/HST registration numbers map to VAT Number; GST/HST validation messages do not.",
            "ALEI maps to Other / Unclassified unless the value clearly means the ISO 17442 Legal Entity Identifier.",
        ],
    },
    "directors_officers_type": _ENTITY_TYPE_RULES,
    "business_entity_type": _ENTITY_TYPE_RULES,
    "ownership_relationship_type": _ENTITY_TYPE_RULES,
    "directors_officers_status": {
        "steps": [
            "Use Active when the person or organization is currently serving in the role.",
            "Use Resigned when departure, removal, retirement, or cessation is confirmed.",
            "Use Other / Unclassified when the status is unclear, blank, or only says Inactive.",
        ],
        "priority": "Confirmed current service maps to Active; confirmed departure maps to Resigned; ambiguity remains Other / Unclassified.",
        "notes": [
            "Inactive does not prove that the person resigned, so it maps to Other / Unclassified.",
        ],
    },
    "ownership_relationship_status": _BUSINESS_STATUS_RULES,
}


FIELD_GUIDANCE: dict[str, dict] = {
    "business_legal_form": {
        "summary": "The legal structure of a business, such as a company, partnership, or trust.",
        "categories": {
            "Sole Proprietorship / Individual Business": _item(
                "A business owned and operated by one person.",
                "Sole trader", "Individual entrepreneur", "Sole proprietorship",
            ),
            "Partnership": _item(
                "A business owned by two or more partners.",
                "General partnership", "Limited partnership", "Joint inheritance rights",
            ),
            "Company": _item(
                "An incorporated organization that is legally separate from its owners.",
                "Limited company", "Corporation", "GmbH", "SARL",
            ),
            "Non-Profit / Cooperative": _item(
                "An organization created for member, community, charitable, or social benefit.",
                "Association", "Foundation", "Cooperative", "Credit union",
            ),
            "Trust / Fund / Scheme": _item(
                "A structure that holds or manages assets for beneficiaries or investors.",
                "Trust", "Investment fund", "Managed scheme",
            ),
            "Foreign Entity / Branch": _item(
                "A foreign organization or a registered branch of another organization.",
                "Foreign company", "Overseas branch", "External company",
            ),
            "Government / Public Sector Entity": _item(
                "A government body or publicly controlled organization.",
                "Municipality", "Ministry", "Public authority",
            ),
            "Other / Unclassified": _item(
                "The legal form is missing, unclear, or does not fit a supported category.",
                "Unknown", "Business name only", "Blank value",
            ),
        },
    },
    "positions_designations": {
        "summary": "A person's or entity's role in the governance, management, ownership, or representation of a business.",
        "note": "This field is country-aware. The same title can mean something different in another country.",
        "categories": {
            "Board Member": _item(
                "A governance role responsible for board-level oversight.",
                "Board member", "Board chair", "Supervisory board member",
            ),
            "Director": _item(
                "A person formally recorded as holding a director role.",
                "Director", "Nominee director", "Assistant director",
            ),
            "Executive Management": _item(
                "A senior role responsible for daily management or business strategy.",
                "CEO", "CFO", "Chief operating officer", "Executive president",
            ),
            "Owner / Controller": _item(
                "A role that establishes ownership or control over the business.",
                "Owner", "Proprietor", "Controlling member", "Partner",
            ),
            "Authorized Representative": _item(
                "A person authorized to represent, sign for, or legally act for the business.",
                "Legal representative", "Authorized signatory", "Procurator", "Liquidator",
            ),
            "Other / Unclassified": _item(
                "The title does not clearly establish one of the supported roles.",
                "Company secretary", "Associate", "Unclear title",
            ),
        },
    },
    "business_status": {
        "summary": "The organization's current legal standing on an official register.",
        "categories": _BUSINESS_STATUS,
    },
    "psc_beneficiary_type": {
        "summary": "The type of ownership or control relationship connected to a business.",
        "categories": {
            "Root Business": _item(
                "The top-level or parent business in the ownership structure.",
                "Root entity", "Parent business",
            ),
            "Owner / Beneficial Owner": _item(
                "A person or entity with a direct or beneficial ownership interest.",
                "Beneficial owner", "Sole shareholder", "Named partner",
            ),
            "Controller": _item(
                "A person or entity exercising control without clearly establishing ownership.",
                "Controller", "Person with significant control",
            ),
            "Other / Unclassified": _item(
                "The relationship is missing, unclear, or does not establish ownership or control.",
                "Unknown relationship", "Unclear member", "Blank value",
            ),
        },
    },
    "brn_type": {
        "summary": "The kind of identifier assigned to a business or organization.",
        "categories": {
            "Business Registration Number": _item(
                "A government-issued number used to register a business or legal entity.",
                "Company number", "Business registry number", "Incorporation number",
            ),
            "Tax ID Number": _item(
                "A government-issued number used for tax administration.",
                "Tax identification number", "TIN", "EIN",
            ),
            "VAT Number": _item(
                "A number used to register a business for value-added tax.",
                "VAT ID", "GST/VAT registration number",
            ),
            "LEI": _item(
                "A 20-character Legal Entity Identifier used in financial markets.",
                "529900T8BM49AURSDO55",
            ),
            "Charity Number": _item(
                "An identifier issued by a charity or non-profit regulator.",
                "Registered charity number", "Non-profit registration number",
            ),
            "Proprietary / Third-party ID": _item(
                "An identifier issued by a commercial provider rather than a government registry.",
                "D-U-N-S number", "Provider-specific entity ID",
            ),
            "Other / Unclassified": _item(
                "The identifier type is missing, unclear, unsupported, or not a business-registration identifier.",
                "Unknown", "SWIFT/BIC", "CAGE code", "ALEI",
            ),
        },
    },
    "directors_officers_type": {
        "summary": "Whether a director or officer record represents a person or an organization.",
        "categories": _ENTITY_TYPE,
    },
    "business_entity_type": {
        "summary": "Whether a party in the business data is a person or an organization.",
        "categories": _ENTITY_TYPE,
    },
    "ownership_relationship_type": {
        "summary": "Whether a party in an ownership relationship is a person or an organization.",
        "categories": _ENTITY_TYPE,
    },
    "directors_officers_status": {
        "summary": "Whether a director or officer currently holds the role.",
        "categories": {
            "Active": _item(
                "The person or organization currently holds the role.",
                "Active", "Current", "Appointed", "In office",
            ),
            "Resigned": _item(
                "The person or organization previously held the role but no longer does.",
                "Resigned", "Removed", "Retired", "Former",
            ),
            "Other / Unclassified": _item(
                "The role status is missing or cannot be determined reliably.",
                "Unknown", "Pending", "Blank value",
            ),
        },
    },
    "ownership_relationship_status": {
        "summary": "The current status of an ownership relationship.",
        "categories": _BUSINESS_STATUS,
    },
}


def validate_guidance(field_specs) -> list[str]:
    """Return human-readable consistency issues between guidance and fields.py."""
    issues: list[str] = []
    for spec in field_specs:
        guidance = FIELD_GUIDANCE.get(spec.key)
        if not guidance:
            issues.append(f"Missing guidance for field {spec.key!r}")
            continue
        configured = set(spec.standard_values)
        documented = set(guidance.get("categories", {}))
        for missing in sorted(configured - documented):
            issues.append(f"Missing guidance for {spec.key!r} category {missing!r}")
        for extra in sorted(documented - configured):
            issues.append(f"Unknown guidance category for {spec.key!r}: {extra!r}")
        if spec.key not in CLASSIFICATION_RULES:
            issues.append(f"Missing classification rules for field {spec.key!r}")
    return issues


def parse_country_rules(prompt_text: str) -> list[dict[str, str]]:
    """Extract the active country-rule Markdown table from a field prompt."""
    rules: list[dict[str, str]] = []
    for line in prompt_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 5 or cells[0] in {"Code", "------"}:
            continue
        if all(re.fullmatch(r"-+", cell) for cell in cells):
            continue
        code, country, board_terms, management_terms, nuance = cells
        if not re.fullmatch(r"[A-Z]{2}", code):
            continue

        def clean(value: str) -> str:
            return value.replace(r"\=", "=").replace(r"\.", ".")

        rules.append({
            "code": code,
            "country": clean(country),
            "board_terms": clean(board_terms),
            "management_terms": clean(management_terms),
            "nuance": clean(nuance),
        })
    return rules
