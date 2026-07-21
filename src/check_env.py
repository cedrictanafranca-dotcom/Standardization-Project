r"""Phase 0 sanity check.

Confirms the environment is wired up correctly WITHOUT spending an API call:
  - the three core libraries import,
  - config loads,
  - the .env-based key loading path works and reports key status.

Run:
    .venv\Scripts\python.exe src\check_env.py

When a real API key is in place, pass --ping to make one trivial live call
to confirm the key actually works.
"""

from __future__ import annotations

import argparse
import sys

import config


def check_imports() -> bool:
    ok = True
    for name in ("anthropic", "pandas", "openpyxl", "dotenv"):
        try:
            module = __import__(name)
            version = getattr(module, "__version__", "?")
            print(f"  [ok] {name:<10} {version}")
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  [!!] {name:<10} import failed: {exc}")
            ok = False
    return ok


def check_folders() -> bool:
    ok = True
    for label, path in (
        ("prompts", config.PROMPTS_DIR),
        ("data", config.DATA_DIR),
        ("output", config.OUTPUT_DIR),
    ):
        exists = path.is_dir()
        mark = "ok" if exists else "!!"
        print(f"  [{mark}] {label:<10} {path}")
        ok = ok and exists
    return ok


def check_key() -> bool:
    if config.has_real_api_key():
        print("  [ok] ANTHROPIC_API_KEY loaded from .env (real key present)")
        return True
    print("  [--] ANTHROPIC_API_KEY not set yet (still placeholder) — expected "
          "until API access is confirmed. Loading path itself works.")
    return True  # not a failure at this stage


def ping() -> bool:
    """One minimal live call to confirm the key works. Only with --ping."""
    import anthropic

    client = anthropic.Anthropic(api_key=config.get_api_key())
    resp = client.messages.create(
        model=config.get_model(),
        max_tokens=5,
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    print(f"  [ok] live API call succeeded, model replied: {text.strip()!r}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 0 environment check")
    parser.add_argument(
        "--ping",
        action="store_true",
        help="make one trivial live Claude API call (needs a real key)",
    )
    args = parser.parse_args()

    print("Model configured:", config.get_model())
    print("\nLibraries:")
    imports_ok = check_imports()
    print("\nFolders:")
    folders_ok = check_folders()
    print("\nAPI key:")
    key_ok = check_key()

    all_ok = imports_ok and folders_ok and key_ok

    if args.ping:
        print("\nLive API ping:")
        try:
            ping()
        except config.MissingAPIKeyError as exc:
            print(f"  [!!] cannot ping: {exc}")
            all_ok = False
        except Exception as exc:  # noqa: BLE001
            print(f"  [!!] live call failed: {exc}")
            all_ok = False

    print("\n" + ("All checks passed." if all_ok else "Some checks FAILED — see above."))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
