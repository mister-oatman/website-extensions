"""Scrape Instagram and TikTok follower counts into a JSON file.

Reads the handles listed in ``instagram_profiles`` and ``tiktok_profiles`` (one
per line, one file per platform), fetches the current follower count for each,
and writes the results to ``site/data.json``.

The CI schedule invokes this daily, but the script itself decides whether to
run today: it paces the runs so the SerpApi search fallback stays within the
billing period's quota (see ``app.quota``).

Run with ``uv run scrape`` (see ``[project.scripts]`` in ``pyproject.toml``).
"""

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from app import quota
from app.services.social import InstagramService, SocialService, TikTokService

logger = logging.getLogger(__name__)

# Repo root is two levels up from this file: scraper/app/main.py -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "site"

PLATFORMS: dict[str, type[SocialService]] = {
    "instagram": InstagramService,
    "tiktok": TikTokService,
}

# Default source file per platform, listing the profiles to scrape.
DEFAULT_INPUTS: dict[str, Path] = {
    "instagram": REPO_ROOT / "instagram_profiles",
    "tiktok": REPO_ROOT / "tiktok_profiles",
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


def scrape_profile(platform: str, username: str) -> dict[str, str | None]:
    """Fetch the follower count for ``username`` on ``platform``.

    Failures are captured in the result rather than raised, so one broken
    profile never aborts the whole run.

    Args:
        platform: The platform key (a key of ``PLATFORMS``).
        username: The handle to look up.

    Returns:
        An entry of ``{"platform": ..., "username": ..., "followers": ...}``.
    """
    service = PLATFORMS[platform]
    try:
        followers = service.get_followers(username)
        logger.info("%s / %s: %s", username, platform, followers)
        return {"platform": platform, "username": username, "followers": followers}
    except Exception as exc:  # noqa: BLE001 - record any scrape failure
        logger.warning("%s / %s failed: %s", username, platform, exc)
        return {"platform": platform, "username": username, "followers": None}


def build_data(profiles_by_platform: dict[str, list[str]]) -> dict:
    """Scrape every profile and assemble the JSON payload.

    Args:
        profiles_by_platform: The usernames to scrape, keyed by platform.

    Returns:
        The serialisable data structure written to ``data.json``.
    """
    accounts = [
        scrape_profile(platform, username)
        for platform, usernames in profiles_by_platform.items()
        for username in usernames
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "platforms": list(PLATFORMS),
        "accounts": accounts,
    }


def main() -> None:
    """Entry point: scrape all profiles and write the site output."""
    parser = argparse.ArgumentParser(description=__doc__)
    for platform in PLATFORMS:
        parser.add_argument(
            f"--{platform}-input",
            type=Path,
            default=DEFAULT_INPUTS[platform],
            help=f"File listing {platform} profiles to scrape (one per line).",
        )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write data.json into.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Scrape regardless of the SerpApi quota pacing (ignore should_scrape).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    profiles_by_platform = {
        platform: read_usernames(getattr(args, f"{platform}_input"))
        for platform in PLATFORMS
    }

    profile_count = sum(len(usernames) for usernames in profiles_by_platform.values())
    if args.force:
        logger.info("Forcing scrape; ignoring the SerpApi quota pacing.")
    else:
        serpapi_quota = quota.serpapi_quota()
        if not quota.should_scrape(
            datetime.now(UTC).date(), serpapi_quota, profile_count
        ):
            logger.info("Not scraping today; leaving the existing output untouched.")
            return

    for platform, usernames in profiles_by_platform.items():
        logger.info("Scraping %d %s profile(s)", len(usernames), platform)

    data = build_data(profiles_by_platform)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "data.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )

    logger.info("Wrote output to %s", args.output_dir)


if __name__ == "__main__":
    main()
