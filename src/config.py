"""Central configuration and secure secret loading.

The Anthropic API key is read from a git-ignored `.env` file at the project
root (or from a real environment variable, which takes precedence). The key is
never hardcoded anywhere in the codebase.

Usage:
    from config import get_api_key, get_model
    key = get_api_key()          # raises if missing/placeholder
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root is the parent of this /src directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Standard project folders (created in Phase 0 / Step 1).
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

DEFAULT_MODEL = "claude-opus-4-8"

# Value shipped in .env / .env.example as a stand-in until a real key exists.
_PLACEHOLDER_PREFIXES = ("sk-ant-REPLACE_ME", "sk-ant-xxxx")

# Load .env once at import time. Real OS env vars are NOT overridden.
load_dotenv(PROJECT_ROOT / ".env", override=False)


class MissingAPIKeyError(RuntimeError):
    """Raised when no usable ANTHROPIC_API_KEY is configured."""


def get_api_key() -> str:
    """Return the Anthropic API key, or raise a clear error if it's not set.

    Raises MissingAPIKeyError if the key is absent or still the placeholder,
    so failures are obvious rather than surfacing as a confusing 401 later.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise MissingAPIKeyError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add "
            "your key (see Section 11 of the brief re: API access)."
        )
    if key.startswith(_PLACEHOLDER_PREFIXES):
        raise MissingAPIKeyError(
            "ANTHROPIC_API_KEY is still the placeholder value. Edit .env and "
            "replace it with a real key."
        )
    return key


def has_real_api_key() -> bool:
    """True if a real (non-placeholder) key is configured, without raising."""
    try:
        get_api_key()
        return True
    except MissingAPIKeyError:
        return False


def get_model() -> str:
    """Return the configured model id, falling back to the project default."""
    return os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
