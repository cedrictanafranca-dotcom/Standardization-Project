"""Deterministic, reusable explanations for standardized mapping decisions."""

from __future__ import annotations


_FIELD_NAMES = {
    "positions_designations": "Positions / Designations taxonomy",
    "business_legal_form": "Business Legal Form taxonomy",
    "business_status": "Business Status taxonomy",
    "psc_beneficiary_type": "PSC / Beneficiary Type taxonomy",
    "brn_type": "BRN Type taxonomy",
    "directors_officers_type": "Directors and Officers Type taxonomy",
    "business_entity_type": "Business Entity Type taxonomy",
    "ownership_relationship_type": "Ownership Relationship Type taxonomy",
    "directors_officers_status": "Directors and Officers Status taxonomy",
    "ownership_relationship_status": "Ownership Relationship Status taxonomy",
}

_LABEL_BASIS = {
    "Board Member": "a governance or board-level role",
    "Director": "a formal director-level role",
    "Executive Management": "an executive or operational management role",
    "Owner / Controller": "ownership or controlling authority",
    "Authorized Representative": "authority to represent or act for the organization",
    "Sole Proprietorship / Individual Business": "a business owned and operated by one individual",
    "Partnership": "a partnership or jointly owned legal arrangement",
    "Company": "an incorporated company or equivalent corporate entity",
    "Non-Profit / Cooperative": "a non-profit, association, foundation, or cooperative form",
    "Trust / Fund / Scheme": "a trust, fund, or scheme structure",
    "Foreign Entity / Branch": "a foreign entity registration or branch structure",
    "Government / Public Sector Entity": "a government or public-sector organization",
    "Active": "an active or currently valid status",
    "Inactive": "an inactive, dissolved, or no-longer-operating status",
    "Pending / Insolvency": "a pending, liquidation, bankruptcy, or insolvency status",
    "Resigned": "a resigned or former office-holder status",
    "Root Business": "the top-level or parent business in the ownership structure",
    "Owner / Beneficial Owner": "direct or beneficial ownership",
    "Controller": "control without necessarily establishing direct ownership",
    "Business Registration Number": "a general business or company registration identifier",
    "Tax ID Number": "a tax-registration identifier",
    "VAT Number": "a value-added-tax registration identifier",
    "LEI": "a Legal Entity Identifier",
    "Charity Number": "a charity or non-profit registration identifier",
    "Proprietary / Third-party ID": "a provider-specific or third-party identifier",
    "Individual": "a natural person rather than an organization",
    "Business": "an organization or legal entity rather than a natural person",
}

_EXPLICIT_TERMS = {
    "Board Member": ("board", "chairman", "chairperson", "commissioner"),
    "Director": ("director", "diretor", "directeur"),
    "Executive Management": ("executive", "manager", "chief", "officer"),
    "Owner / Controller": ("owner", "controller", "proprietor", "shareholder"),
    "Authorized Representative": ("representative", "agent", "procurator", "attorney"),
    "Company": ("company", "corporation", "corp", "limited", "ltd", "gmbh", "sarl"),
    "Partnership": ("partnership", "partners", "partnerships"),
    "Non-Profit / Cooperative": ("non-profit", "nonprofit", "foundation", "association", "cooperative"),
    "Trust / Fund / Scheme": ("trust", "fund", "scheme"),
    "Foreign Entity / Branch": ("foreign", "branch"),
    "Government / Public Sector Entity": ("government", "public sector", "municipal", "state-owned"),
    "Active": ("active", "current", "valid"),
    "Inactive": ("inactive", "dissolved", "closed", "terminated"),
    "Pending / Insolvency": ("pending", "insolvent", "insolvency", "bankrupt", "liquidation"),
    "Resigned": ("resigned", "former", "ceased"),
    "Owner / Beneficial Owner": ("beneficial", "owner", "shareholder", "partner"),
    "Controller": ("controller", "control"),
    "Business Registration Number": ("registration", "registry", "company number", "business number"),
    "Tax ID Number": ("tax", "tin"),
    "VAT Number": ("vat", "value added tax"),
    "LEI": ("lei", "legal entity identifier"),
    "Charity Number": ("charity", "non-profit number", "nonprofit number"),
    "Individual": ("individual", "person", "natural person"),
    "Business": ("business", "company", "entity", "organization", "corporation"),
}


def _clean_sentence(text: str) -> str:
    clean = " ".join(str(text or "").strip().strip('"').split())
    if clean and clean[-1] not in ".!?":
        clean += "."
    return clean


def _taxonomy_basis(
    field_key: str | None,
    raw_value: str,
    standardized_value: str,
    country: str = "",
) -> str:
    raw = " ".join(str(raw_value or "").split())
    taxonomy = _FIELD_NAMES.get(field_key or "", "applicable standardization taxonomy")

    if not raw:
        return (
            f"No source value was provided, so there is no category-specific evidence; "
            f"the {taxonomy} catch-all is used and the row requires review."
        )

    if standardized_value == "ERROR - Not Classified (API Failure)":
        return (
            "Classification could not be completed because the API request failed; "
            "the row is marked as an error and requires review."
        )

    if standardized_value == "Other / Unclassified":
        return (
            f'"{raw}" does not provide sufficient evidence for one of the named '
            f"categories in the {taxonomy}, so the catch-all value "
            '"Other / Unclassified" is used.'
        )

    basis = _LABEL_BASIS.get(
        standardized_value,
        f'the definition of "{standardized_value}"',
    )
    raw_lower = raw.casefold()
    matched = next(
        (term for term in _EXPLICIT_TERMS.get(standardized_value, ()) if term in raw_lower),
        None,
    )
    country_prefix = f"For {country}, " if country and field_key == "positions_designations" else ""
    if matched:
        return (
            f'{country_prefix}"{raw}" contains the role or entity signal "{matched}", '
            f'which indicates {basis} and maps to "{standardized_value}" in the {taxonomy}.'
        )
    return (
        f'{country_prefix}"{raw}" is treated as {basis}, which maps to '
        f'"{standardized_value}" in the {taxonomy}.'
    )


def build_mapping_reason(
    *,
    field_key: str | None,
    raw_value: str,
    standardized_value: str,
    source: str,
    country: str = "",
    existing_reason: str = "",
) -> str:
    """Build a substantive taxonomy explanation plus optional provenance."""
    basis = _taxonomy_basis(field_key, raw_value, standardized_value, country)
    model_reason = _clean_sentence(existing_reason)
    if model_reason and model_reason.casefold() not in basis.casefold():
        basis = f"{model_reason} {basis}"

    provenance = {
        "reviewed_country": "This exact country-and-value decision was previously confirmed during review.",
        "reviewed_global": "This exact value decision was previously confirmed during review.",
        "historical_country": "This taxonomy interpretation is also supported by an approved historical mapping for this country.",
        "historical_global": "This taxonomy interpretation is also supported by an approved historical mapping.",
        "approved_alias": "An approved alias rule also recognizes this wording as an equivalent form.",
        "similarity": "The decision is additionally supported by a closely matching approved value with the same canonical label.",
        "model": "The classification model applied the taxonomy to this previously unresolved value.",
        "system_artifact": "The value also matches the system-artifact pattern and is intentionally routed for review.",
        "placeholder": "The value is a recognized missing-data placeholder rather than a substantive business value.",
        "api_failure": "No semantic mapping was accepted because processing failed.",
    }.get(source, "")
    return " ".join(part for part in (basis, provenance) if part).strip()


def build_reviewed_selection_reason(
    *,
    field_key: str | None,
    raw_value: str,
    standardized_value: str,
    country: str = "",
    previous_value: str = "",
    confirmed: bool = False,
) -> str:
    """Explain the final value chosen in the flagged-review interface."""
    basis = _taxonomy_basis(field_key, raw_value, standardized_value, country)
    if confirmed:
        action = "The reviewer confirmed the proposed classification."
    elif previous_value:
        action = (
            f'The reviewer changed the classification from "{previous_value}" to '
            f'"{standardized_value}".'
        )
    else:
        action = f'The reviewer selected "{standardized_value}" as the final classification.'
    return f"{basis} {action}"
