"""Render SVG follower-count badges per account into ``site/badges/``.

The published ``data.json`` is only useful to a page that runs JavaScript. A
badge is the pure-HTML alternative: a small self-contained SVG per account that
a page embeds with ``<img src=".../badges/<username>-<platform>-<variant>.svg">``
and that refreshes whenever the file is republished. Each account is rendered in
every variant in ``BADGE_VARIANTS``: a ``white`` and a ``black`` count-plus-logo,
and ``name-white``/``name-black`` that prefix the platform name (in caps) and
drop the logo — so the page can pick the colour and layout that suit it.

Badges are written as part of a normal scrape (``app.main``) and can also be
regenerated on their own with ``uv run render-badges``, which reads an existing
``data.json`` and touches no network or SerpApi quota — handy for iterating on
the badge design without scraping again.
"""

import argparse
import logging
import re
from pathlib import Path
from typing import NamedTuple
from xml.sax.saxutils import escape

from app import datafile

logger = logging.getLogger(__name__)

# Repo root is two levels up from this file: scraper/app/badges.py -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "site"

# Shown as the value when a profile's follower count is unavailable (the scrape
# failed and there was no previous count to carry forward).
UNAVAILABLE_VALUE = "—"


class BadgeVariant(NamedTuple):
    """One rendering of a badge on an otherwise transparent background."""

    color: str
    """Fill colour shared by the count and the logo/label."""
    show_name: bool
    """If true, prefix the count with the platform name in caps and omit the
    logo; if false, follow the count with the platform logo."""


# Every account is rendered once per variant below. ``white``/``black`` are the
# count followed by the platform logo; ``name-white``/``name-black`` prefix the
# count with the platform name in all caps and drop the logo. The colour is the
# trailing token of the key, which is also the filename suffix.
BADGE_VARIANTS: dict[str, BadgeVariant] = {
    "logo-white": BadgeVariant("#ffffff", show_name=False),
    "logo-black": BadgeVariant("#000000", show_name=False),
    "name-white": BadgeVariant("#ffffff", show_name=True),
    "name-black": BadgeVariant("#000000", show_name=True),
}
FONT_SIZE = 20
BADGE_HEIGHT = 28

# Inter, normal style, extra-bold. Embedded SVGs can't pull fonts from the host
# page, so this only renders in Inter for viewers who have it installed locally;
# the sans-serif fallback covers everyone else.
FONT_FAMILY = "Inter, sans-serif"
FONT_STYLE = "normal"
FONT_WEIGHT = 800

# Rendered size (px) of the 24x24 logo glyph and the gap between it and the count.
LOGO_SIZE = 22
LOGO_GAP = 6

# Fraction of the font size a single character is assumed to advance, plus the
# horizontal padding on each side. Only used to size the SVG box, so a loose
# estimate is fine.
_CHAR_WIDTH_EM = 0.64
_H_PADDING = 6

# Official brand glyphs (24x24 viewBox, from Simple Icons), drawn after the
# count to mark the platform.
_LOGO_PATHS: dict[str, str] = {
    "instagram": "M7.0301.084c-1.2768.0602-2.1487.264-2.911.5634-.7888.3075-1.4575.72-2.1228 1.3877-.6652.6677-1.075 1.3368-1.3802 2.127-.2954.7638-.4956 1.6365-.552 2.914-.0564 1.2775-.0689 1.6882-.0626 4.947.0062 3.2586.0206 3.6671.0825 4.9473.061 1.2765.264 2.1482.5635 2.9107.308.7889.72 1.4573 1.388 2.1228.6679.6655 1.3365 1.0743 2.1285 1.38.7632.295 1.6361.4961 2.9134.552 1.2773.056 1.6884.069 4.9462.0627 3.2578-.0062 3.668-.0207 4.9478-.0814 1.28-.0607 2.147-.2652 2.9098-.5633.7889-.3086 1.4578-.72 2.1228-1.3881.665-.6682 1.0745-1.3378 1.3795-2.1284.2957-.7632.4966-1.636.552-2.9124.056-1.2809.0692-1.6898.063-4.948-.0063-3.2583-.021-3.6668-.0817-4.9465-.0607-1.2797-.264-2.1487-.5633-2.9117-.3084-.7889-.72-1.4568-1.3876-2.1228C21.2982 1.33 20.628.9208 19.8378.6165 19.074.321 18.2017.1197 16.9244.0645 15.6471.0093 15.236-.005 11.977.0014 8.718.0076 8.31.0215 7.0301.0839m.1402 21.6932c-1.17-.0509-1.8053-.2453-2.2287-.408-.5606-.216-.96-.4771-1.3819-.895-.422-.4178-.6811-.8186-.9-1.378-.1644-.4234-.3624-1.058-.4171-2.228-.0595-1.2645-.072-1.6442-.079-4.848-.007-3.2037.0053-3.583.0607-4.848.05-1.169.2456-1.805.408-2.2282.216-.5613.4762-.96.895-1.3816.4188-.4217.8184-.6814 1.3783-.9003.423-.1651 1.0575-.3614 2.227-.4171 1.2655-.06 1.6447-.072 4.848-.079 3.2033-.007 3.5835.005 4.8495.0608 1.169.0508 1.8053.2445 2.228.408.5608.216.96.4754 1.3816.895.4217.4194.6816.8176.9005 1.3787.1653.4217.3617 1.056.4169 2.2263.0602 1.2655.0739 1.645.0796 4.848.0058 3.203-.0055 3.5834-.061 4.848-.051 1.17-.245 1.8055-.408 2.2294-.216.5604-.4763.96-.8954 1.3814-.419.4215-.8181.6811-1.3783.9-.4224.1649-1.0577.3617-2.2262.4174-1.2656.0595-1.6448.072-4.8493.079-3.2045.007-3.5825-.006-4.848-.0608M16.953 5.5864A1.44 1.44 0 1 0 18.39 4.144a1.44 1.44 0 0 0-1.437 1.4424M5.8385 12.012c.0067 3.4032 2.7706 6.1557 6.173 6.1493 3.4026-.0065 6.157-2.7701 6.1506-6.1733-.0065-3.4032-2.771-6.1565-6.174-6.1498-3.403.0067-6.156 2.771-6.1496 6.1738M8 12.0077a4 4 0 1 1 4.008 3.9921A3.9996 3.9996 0 0 1 8 12.0077",
    "tiktok": "M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z",
}


def _text_width(text: str) -> int:
    """Return an approximate rendered width in px for ``text``."""
    return round(len(text) * FONT_SIZE * _CHAR_WIDTH_EM)


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
    slug = re.sub(r"[^a-z0-9._-]+", "_", text.strip().lower()).strip()
    return slug or "_"


def badge_filename(platform: str, username: str, variant: str) -> str:
    """Return the SVG filename, e.g. ``alinafrie-instagram-white.svg``."""
    return f"{_slug(username)}-{_slug(platform)}-{_slug(variant)}.svg"


def _logo_markup(platform: str, x: float, y: float, color: str) -> str:
    """Return the platform-logo glyph placed at ``(x, y)`` in ``color``, or ``""``.

    The 24x24 glyph is scaled to ``LOGO_SIZE`` and filled with ``color`` to match
    the count. An unknown platform yields no logo.

    Args:
        platform: The platform key (matched case-insensitively).
        x: Left edge of the logo in the badge's coordinate space.
        y: Top edge of the logo in the badge's coordinate space.
        color: Fill colour for the glyph.

    Returns:
        The logo markup, or an empty string when the platform has no glyph.
    """
    path = _LOGO_PATHS.get(platform.lower())
    if not path:
        return ""
    scale = LOGO_SIZE / 24
    transform = f"translate({x:.2f},{y:.2f}) scale({scale:.4f})"
    return f'<path d="{path}" transform="{transform}" fill="{color}"/>'


def render_badge(
    platform: str, followers: str | None, color: str, show_name: bool = False
) -> str:
    """Return a self-contained SVG of the follower count for one account.

    Two layouts, both Inter text filled with ``color`` on a transparent
    background (so a light or dark ``color`` can suit either page):

    - ``show_name`` false: the count followed by the platform logo.
    - ``show_name`` true: the platform name in all caps before the count, with
      no logo.

    Args:
        platform: The platform key (e.g. ``"instagram"``), selecting the logo
            and supplying the name.
        followers: The follower count string (e.g. ``"251K"``), or ``None`` when
            unavailable, in which case a placeholder is shown.
        color: Fill colour for the count and the logo/label.
        show_name: Choose the name-prefixed, logo-less layout.

    Returns:
        The SVG document as a string.
    """
    value = followers if followers else UNAVAILABLE_VALUE
    if show_name:
        text = f"{platform.upper()} {value}"
        has_logo = False
    else:
        text = value
        has_logo = platform.lower() in _LOGO_PATHS
    text_esc = escape(text)
    text_w = _text_width(text)

    logo_x = _H_PADDING + text_w + LOGO_GAP
    logo_y = (BADGE_HEIGHT - LOGO_SIZE) / 2
    content_w = text_w + (LOGO_GAP + LOGO_SIZE if has_logo else 0)
    width = content_w + 2 * _H_PADDING
    baseline = round(BADGE_HEIGHT / 2 + FONT_SIZE * 0.34)  # vertical centre

    logo = _logo_markup(platform, logo_x, logo_y, color) if has_logo else ""

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{BADGE_HEIGHT}" role="img" aria-label="{text_esc}">'
        f"<title>{text_esc}</title>"
        f'<text x="{_H_PADDING}" y="{baseline}" text-anchor="start" fill="{color}" '
        f'font-family="{FONT_FAMILY}" font-style="{FONT_STYLE}" '
        f'font-weight="{FONT_WEIGHT}" font-size="{FONT_SIZE}">{text_esc}</text>'
        f"{logo}"
        "</svg>\n"
    )


def write_badges(data: dict, output_dir: Path) -> int:
    """Write one SVG badge per account and colour variant into ``output_dir/badges``.

    Any pre-existing ``*.svg`` in the badges directory is removed first, so a
    profile dropped from the input files no longer leaves a stale badge behind.

    Args:
        data: A parsed ``data.json`` payload with an ``accounts`` list.
        output_dir: The site output directory (``badges/`` is created inside).

    Returns:
        The number of badge files written (accounts × variants).
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
        for variant_name, variant in BADGE_VARIANTS.items():
            svg = render_badge(platform, followers, variant.color, variant.show_name)
            filename = badge_filename(platform, username, variant_name)
            (badges_dir / filename).write_text(svg, encoding="utf-8")
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
