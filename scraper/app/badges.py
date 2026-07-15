"""Render one SVG follower-count badge per account into ``site/badges/``.

The published ``data.json`` is only useful to a page that runs JavaScript. A
badge is the pure-HTML alternative: a small self-contained SVG per account that
a page embeds with ``<img src=".../badges/<username>-<platform>.svg">`` and that
refreshes whenever the file is republished.

Badges are written as part of a normal scrape (``app.main``) and can also be
regenerated on their own with ``uv run render-badges``, which reads an existing
``data.json`` and touches no network or SerpApi quota — handy for iterating on
the badge design without scraping again.
"""

import argparse
import logging
import re
from pathlib import Path
from xml.sax.saxutils import escape

from app import datafile

logger = logging.getLogger(__name__)

# Repo root is two levels up from this file: scraper/app/badges.py -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "site"

# Shown as the value when a profile's follower count is unavailable (the scrape
# failed and there was no previous count to carry forward).
UNAVAILABLE_VALUE = "—"

# White text on a transparent background, so the badge drops onto a dark section
# of the page and inherits nothing from it.
TEXT_COLOR = "#ffffff"
FONT_SIZE = 14
BADGE_HEIGHT = 20

# Inter, normal style, extra-bold. Embedded SVGs can't pull fonts from the host
# page, so this only renders in Inter for viewers who have it installed locally;
# the sans-serif fallback covers everyone else.
FONT_FAMILY = "Inter, sans-serif"
FONT_STYLE = "normal"
FONT_WEIGHT = 800

# Rough advance width (px) per character at the font size and weight above, plus
# a little horizontal padding. Only used to size the SVG box; the text is centre-
# anchored, so a loose estimate is fine.
_CHAR_WIDTH = 9.5
_H_PADDING = 4


def _text_width(text: str) -> int:
    """Return an approximate rendered width in px for ``text``."""
    return round(len(text) * _CHAR_WIDTH)


def _slug(text: str) -> str:
    """Return a filesystem- and URL-safe slug for a handle or platform name.

    Lower-cases and replaces any run of unsafe characters with ``_``. This
    matches the case-insensitive lookup the page-side JavaScript uses, so badge
    URLs are predictable (always lower-case).

    Args:
        text: The raw username or platform string.

    Returns:
        A slug containing only ``[a-z0-9._-]``, never empty.
    """
    slug = re.sub(r"[^a-z0-9._-]+", "_", text.strip().lower()).strip("_")
    return slug or "_"


def badge_filename(platform: str, username: str) -> str:
    """Return the SVG filename for an account, e.g. ``alinafrie-instagram.svg``."""
    return f"{_slug(username)}-{_slug(platform)}.svg"


def render_badge(followers: str | None) -> str:
    """Return a self-contained SVG showing only the follower count.

    The count is rendered as plain white text on a transparent background — no
    label, pill, or platform name — so it drops onto a dark section of the page
    like inline text.

    Args:
        followers: The follower count string (e.g. ``"251K"``), or ``None`` when
            unavailable, in which case a placeholder is shown.

    Returns:
        The SVG document as a string.
    """
    value = followers if followers else UNAVAILABLE_VALUE
    width = _text_width(value) + 2 * _H_PADDING
    mid = width / 2
    baseline = round(BADGE_HEIGHT * 0.72)  # visually centre the text vertically
    value_x = escape(value)

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{BADGE_HEIGHT}" role="img" aria-label="{value_x}">'
        f"<title>{value_x}</title>"
        f'<text x="{mid}" y="{baseline}" text-anchor="middle" fill="{TEXT_COLOR}" '
        f'font-family="{FONT_FAMILY}" font-style="{FONT_STYLE}" '
        f'font-weight="{FONT_WEIGHT}" font-size="{FONT_SIZE}">{value_x}</text>'
        "</svg>\n"
    )


def write_badges(data: dict, output_dir: Path) -> int:
    """Write one SVG badge per account into ``output_dir/badges``.

    Any pre-existing ``*.svg`` in the badges directory is removed first, so a
    profile dropped from the input files no longer leaves a stale badge behind.

    Args:
        data: A parsed ``data.json`` payload with an ``accounts`` list.
        output_dir: The site output directory (``badges/`` is created inside).

    Returns:
        The number of badges written.
    """
    badges_dir = output_dir / "badges"
    badges_dir.mkdir(parents=True, exist_ok=True)
    for stale in badges_dir.glob("*.svg"):
        stale.unlink()

    count = 0
    for account in data.get("accounts", []):
        platform = account.get("platform")
        username = account.get("username")
        if not isinstance(platform, str) or not isinstance(username, str):
            continue
        followers = account.get("followers")
        followers = followers if isinstance(followers, str) else None
        svg = render_badge(followers)
        (badges_dir / badge_filename(platform, username)).write_text(
            svg, encoding="utf-8"
        )
        count += 1
    return count


def main() -> None:
    """Entry point for ``render-badges``: rebuild badges from an existing data.json.

    Reads a previously written ``data.json`` (local copy preferred, published
    copy as a fallback) and regenerates the badges without scraping. No profile
    is fetched and no SerpApi search is spent.
    """
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory holding data.json and the badges/ subdirectory to write.",
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        default=None,
        help="data.json to read (defaults to <output-dir>/data.json).",
    )
    parser.add_argument(
        "--data-url",
        default=datafile.DEFAULT_DATA_URL,
        help="Published data.json to fall back to if the local file is missing.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    local = args.data_file or (args.output_dir / "data.json")
    data = datafile.load_data(local, args.data_url)
    if not data:
        logger.error(
            "No data.json available (looked at %s, then %s); nothing to render.",
            local,
            args.data_url,
        )
        raise SystemExit(1)

    count = write_badges(data, args.output_dir)
    logger.info("Wrote %d badge(s) to %s", count, args.output_dir / "badges")


if __name__ == "__main__":
    main()
