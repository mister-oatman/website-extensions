"""Load a previously written ``data.json`` from disk or its published URL.

Two callers need to read a ``data.json`` that an earlier run produced: the
scraper's carry-forward fallback (``app.main``) and the standalone badge
renderer (``app.badges``). Both want the same best-effort semantics — prefer a
local copy, fall back to the published GitHub Pages copy, and degrade to
``None`` on any problem (missing file, offline, 404, bad JSON) so the caller can
carry on without it. Keeping that logic here avoids duplicating it and keeps
``main`` and ``badges`` free of an import cycle.
"""

import json
import logging
from pathlib import Path

from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

# Published location of the last run's data.json (GitHub Pages). site/ is
# gitignored and CI starts from a clean checkout, so on CI this published copy
# is the only place the last run's output survives.
DEFAULT_DATA_URL = "https://mister-oatman.github.io/website-extensions/data.json"

# Seconds to wait for the published data.json before giving up on it.
DATA_TIMEOUT_S = 30


def read_data_file(path: Path) -> dict | None:
    """Return the parsed ``data.json`` at ``path``, or ``None`` if unavailable.

    A missing or unreadable file is not an error here — the caller treats the
    data as a best-effort input — so failures are logged and swallowed.

    Args:
        path: Location of a previously written ``data.json``.

    Returns:
        The parsed payload, or ``None`` if the file is absent or unparseable.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("Could not read data at %s (%s).", path, exc)
        return None
    return data if isinstance(data, dict) else None


def fetch_data_url(url: str) -> dict | None:
    """Return the parsed ``data.json`` published at ``url``, or ``None``.

    Used on CI, where the previous run's output survives only on the published
    page. Any failure (offline, 404 before the first deploy, bad JSON) is logged
    and swallowed so the caller continues without it.

    Args:
        url: URL of the published ``data.json``.

    Returns:
        The parsed payload, or ``None`` if it could not be fetched or parsed.
    """
    try:
        response = curl_requests.get(url, timeout=DATA_TIMEOUT_S)
        if response.status_code != 200:
            logger.warning(
                "Data fetch from %s returned HTTP %d.", url, response.status_code
            )
            return None
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - the fallback is best-effort
        logger.warning("Could not fetch data from %s (%s).", url, exc)
        return None
    return data if isinstance(data, dict) else None


def load_data(local_path: Path, url: str) -> dict | None:
    """Return a previously written payload, preferring local, then the URL.

    Args:
        local_path: Location of the local ``data.json`` to prefer.
        url: URL of the published ``data.json`` to fall back to.

    Returns:
        The parsed payload, or ``None`` if neither source is available.
    """
    return read_data_file(local_path) or fetch_data_url(url)
