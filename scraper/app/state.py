"""Persistent scrape state shared between runs.

The state lives in a small JSON file (``.scraper-state.json`` in the repo
root) that CI caches between runs. It only stores optimisations — currently
which search prefix last worked per platform — so losing it is harmless.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Repo root is two levels up from this file: scraper/app/state.py -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / ".scraper-state.json"
"""Location of the state file; CI caches this path between runs."""

_SEARCH_PREFIXES_KEY = "search_prefixes"


def _load() -> dict:
    """Read the state file, returning an empty state if missing or corrupt."""
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning(
            "Could not read state file %s (%s); starting fresh.", STATE_PATH, exc
        )
        return {}
    return state if isinstance(state, dict) else {}


def _save(state: dict) -> None:
    """Write ``state`` to the state file, logging (not raising) on failure."""
    try:
        STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write state file %s (%s).", STATE_PATH, exc)


def get_search_prefix(platform: str) -> str | None:
    """Return the search prefix that last worked for ``platform``, if any.

    Args:
        platform: The platform key, e.g. ``"instagram"``.

    Returns:
        The memorised prefix (``""`` or ``"site:"``), or ``None`` if no
        successful search has been recorded yet.
    """
    prefix = _load().get(_SEARCH_PREFIXES_KEY, {}).get(platform)
    return prefix if isinstance(prefix, str) else None


def set_search_prefix(platform: str, prefix: str) -> None:
    """Remember ``prefix`` as the working search prefix for ``platform``.

    Args:
        platform: The platform key, e.g. ``"instagram"``.
        prefix: The prefix that just produced a result (``""`` or ``"site:"``).
    """
    state = _load()
    if state.get(_SEARCH_PREFIXES_KEY, {}).get(platform) == prefix:
        return
    state.setdefault(_SEARCH_PREFIXES_KEY, {})[platform] = prefix
    _save(state)
