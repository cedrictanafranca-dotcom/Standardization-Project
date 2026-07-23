"""Correction queue — submit, review, and approve human corrections.

Workflow:
  1. Reviewer runs a file, downloads the result, edits the Standardized Value
     column for rows they disagree with, and re-uploads the corrected file.
     app.py diffs the two files and calls add_to_queue().

  2. Product person opens the Review Corrections page, sees pending items,
     adds a note, optionally flags for prompt update, and approves or rejects.

  3. Approved corrections are written into data/master_lookup.json so future
     runs skip the API for those values entirely.

Queue file: data/pending_corrections.json
  [
    {
      "id":                 "<uuid4>",
      "submitted_at":       "<ISO-8601>",
      "submitted_by":       "Sarah (Compliance)",
      "country":            "argentina",        # "" = country-agnostic
      "raw_value":          "General Manager",
      "field_key":          "positions_designations",
      "field_display":      "Positions / Designations",
      "original":           "Other / Unclassified",
      "proposed":           "Executive Management",
      "status":             "pending" | "approved" | "rejected",
      "reviewed_at":        null | "<ISO-8601>",
      "reviewer_note":      "",
      "needs_prompt_update": false,
      "source":             "user" | "demo"
    },
    ...
  ]
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

QUEUE_FILE = config.DATA_DIR / "pending_corrections.json"
LOOKUP_FILE = config.DATA_DIR / "master_lookup.json"


# ---------------------------------------------------------------------------
# Normalisation (matches master_lookup._norm / standardize_file._norm_key)
# ---------------------------------------------------------------------------

def _norm(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).split())


# ---------------------------------------------------------------------------
# Queue I/O
# ---------------------------------------------------------------------------

def load_queue() -> list[dict]:
    if not QUEUE_FILE.exists():
        return []
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_queue(queue: list[dict]) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")


def get_pending() -> list[dict]:
    return [c for c in load_queue() if c["status"] == "pending"]


def get_history() -> list[dict]:
    return [c for c in load_queue() if c["status"] != "pending"]


# ---------------------------------------------------------------------------
# Building correction entries
# ---------------------------------------------------------------------------

def make_correction(
    field_key: str,
    field_display: str,
    raw_value: str,
    original: str,
    proposed: str,
    country: str = "",
    submitted_by: str = "",
    source: str = "user",
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "submitted_by": submitted_by,
        "country": country,
        "raw_value": raw_value,
        "field_key": field_key,
        "field_display": field_display,
        "original": original,
        "proposed": proposed,
        "status": "pending",
        "reviewed_at": None,
        "reviewer_note": "",
        "needs_prompt_update": False,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Queue operations
# ---------------------------------------------------------------------------

def add_to_queue(corrections: list[dict]) -> int:
    """Add corrections to the queue, skipping pending duplicates.
    Returns count actually added."""
    queue = load_queue()
    existing = {
        (_norm(c["field_key"]), _norm(c["raw_value"]), _norm(c.get("country", "")))
        for c in queue if c["status"] == "pending"
    }
    added = 0
    for c in corrections:
        key = (_norm(c["field_key"]), _norm(c["raw_value"]), _norm(c.get("country", "")))
        if key in existing:
            continue
        queue.append(c)
        existing.add(key)
        added += 1
    save_queue(queue)
    return added


def approve(
    correction_id: str,
    note: str = "",
    needs_prompt_update: bool = False,
) -> bool:
    """Approve a pending correction and write it to the master lookup."""
    queue = load_queue()
    for c in queue:
        if c["id"] == correction_id and c["status"] == "pending":
            c["status"] = "approved"
            c["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            c["reviewer_note"] = note
            c["needs_prompt_update"] = needs_prompt_update
            save_queue(queue)
            _apply_to_lookup(c)
            return True
    return False


def reject(correction_id: str, note: str = "") -> bool:
    """Reject a pending correction."""
    queue = load_queue()
    for c in queue:
        if c["id"] == correction_id and c["status"] == "pending":
            c["status"] = "rejected"
            c["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            c["reviewer_note"] = note
            save_queue(queue)
            return True
    return False


def clear_demo_data() -> int:
    """Remove all corrections with source='demo'. Returns count removed."""
    queue = load_queue()
    before = len(queue)
    queue = [c for c in queue if c.get("source") != "demo"]
    save_queue(queue)
    return before - len(queue)


# ---------------------------------------------------------------------------
# Apply approved correction to master_lookup.json
# ---------------------------------------------------------------------------

def _apply_to_lookup(correction: dict) -> None:
    """Write an approved correction into master_lookup.json.

    Adds a country-specific entry if country is set, otherwise a consistent
    (country-agnostic) entry. Overwrites any existing entry for that key —
    human-approved corrections take precedence over API-generated ones.
    """
    if LOOKUP_FILE.exists():
        data = json.loads(LOOKUP_FILE.read_text(encoding="utf-8"))
    else:
        data = {}

    fk = correction["field_key"]
    raw_n = _norm(correction["raw_value"])
    country_n = _norm(correction.get("country", ""))
    proposed = correction["proposed"]

    if fk not in data:
        data[fk] = {"consistent": {}, "by_country": {}}

    if country_n:
        data[fk].setdefault("by_country", {}).setdefault(country_n, {})[raw_n] = proposed
    else:
        data[fk].setdefault("consistent", {})[raw_n] = proposed

    LOOKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOOKUP_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def load_demo_corrections() -> list[dict]:
    """Return 5 realistic demo corrections seeded from actual classification output."""
    now = datetime.now(timezone.utc)
    yesterday = now.replace(hour=8, minute=30, second=0, microsecond=0).isoformat()
    today = now.replace(hour=9, minute=15, second=0, microsecond=0).isoformat()

    return [
        {
            "id": "demo-001",
            "submitted_at": yesterday,
            "submitted_by": "Sarah (Compliance)",
            "country": "Argentina",
            "raw_value": "General Manager",
            "field_key": "positions_designations",
            "field_display": "Positions / Designations",
            "original": "Other / Unclassified",
            "proposed": "Executive Management",
            "status": "pending",
            "reviewed_at": None,
            "reviewer_note": "",
            "needs_prompt_update": False,
            "source": "demo",
        },
        {
            "id": "demo-002",
            "submitted_at": yesterday,
            "submitted_by": "Sarah (Compliance)",
            "country": "Argentina",
            "raw_value": "Branch Manager",
            "field_key": "positions_designations",
            "field_display": "Positions / Designations",
            "original": "Other / Unclassified",
            "proposed": "Executive Management",
            "status": "pending",
            "reviewed_at": None,
            "reviewer_note": "",
            "needs_prompt_update": False,
            "source": "demo",
        },
        {
            "id": "demo-003",
            "submitted_at": today,
            "submitted_by": "James (Product)",
            "country": "Australia",
            "raw_value": "Executive Director",
            "field_key": "positions_designations",
            "field_display": "Positions / Designations",
            "original": "Executive Management",
            "proposed": "Board Member",
            "status": "pending",
            "reviewed_at": None,
            "reviewer_note": "",
            "needs_prompt_update": False,
            "source": "demo",
        },
        {
            "id": "demo-004",
            "submitted_at": yesterday,
            "submitted_by": "Sarah (Compliance)",
            "country": "Argentina",
            "raw_value": "Syndic",
            "field_key": "positions_designations",
            "field_display": "Positions / Designations",
            "original": "Authorized Representative",
            "proposed": "Board Member",
            "status": "pending",
            "reviewed_at": None,
            "reviewer_note": "",
            "needs_prompt_update": False,
            "source": "demo",
        },
        {
            "id": "demo-005",
            "submitted_at": today,
            "submitted_by": "James (Product)",
            "country": "Malaysia",
            "raw_value": "Berhad",
            "field_key": "business_legal_form",
            "field_display": "Business Legal Form (BLF)",
            "original": "Other / Unclassified",
            "proposed": "Company",
            "status": "pending",
            "reviewed_at": None,
            "reviewer_note": "",
            "needs_prompt_update": False,
            "source": "demo",
        },
    ]
