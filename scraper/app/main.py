"""Scrape Instagram and TikTok follower counts into a JSON file.

Reads the handles listed in ``usernames_to_scrape`` (one per line), fetches the
current follower count for each on Instagram and TikTok, and writes the results
to ``site/data.json``.

Run with ``uv run scrape`` (see ``[project.scripts]`` in ``pyproject.toml``).
"""

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.services.social import InstagramService, SocialService, TikTokService

logger = logging.getLogger(__name__)

# Repo root is two levels up from this file: scraper/app/main.py -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "usernames_to_scrape"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "site"

PLATFORMS: dict[str, type[SocialService]] = {
    "instagram": InstagramService,
    "tiktok": TikTokService,
}


def read_usernames(path: Path) -> list[str]:
    """Read handles from ``path``, one per line, ignoring blanks.

    Args:
        path: The file listing usernames to scrape.

    Returns:
        The list of non-empty, stripped usernames.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    return [stripped for line in lines if (stripped := line.strip())]


def scrape_user(username: str) -> dict[str, dict[str, str | None]]:
    """Fetch the follower count for ``username`` on every platform.

    Failures on a single platform are captured in the result rather than raised,
    so one broken profile never aborts the whole run.

    Args:
        username: The handle to look up.

    Returns:
        A mapping of platform name to ``{"followers": ..., "error": ...}``.
    """
    result: dict[str, dict[str, str | None]] = {}
    for platform, service in PLATFORMS.items():
        try:
            followers = service.get_followers(username)
            result[platform] = {"followers": followers, "error": None}
            logger.info("%s / %s: %s", username, platform, followers)
        except Exception as exc:  # noqa: BLE001 - record any scrape failure
            result[platform] = {"followers": None, "error": str(exc)}
            logger.warning("%s / %s failed: %s", username, platform, exc)
    return result


def build_data(usernames: list[str]) -> dict:
    """Scrape every username and assemble the JSON payload.

    Args:
        usernames: The handles to scrape.

    Returns:
        The serialisable data structure written to ``data.json``.
    """
    accounts = [
        {"username": username, **scrape_user(username)} for username in usernames
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "platforms": list(PLATFORMS),
        "accounts": accounts,
    }


def main() -> None:
    """Entry point: scrape all usernames and write the site output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="File listing usernames to scrape (one per line).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write data.json into.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    usernames = read_usernames(args.input)
    logger.info("Scraping %d username(s) from %s", len(usernames), args.input)

    data = build_data(usernames)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "data.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )

    logger.info("Wrote output to %s", args.output_dir)


if __name__ == "__main__":
    main()
