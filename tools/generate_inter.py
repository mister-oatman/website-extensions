"""Regenerate ``scraper/app/inter.py`` from an Inter ExtraBold font file.

The badges draw their text as vector outlines rather than as SVG ``<text>``,
because an SVG embedded with ``<img>`` can only use fonts the viewer happens to
have installed — and with Inter missing, the fallback's metrics are not the ones
the badge was laid out with, so the logo lands at the wrong distance from the
count. Outlines take the viewer's fonts out of the picture entirely.

This script is run by hand, not by the scraper, and only when the badge font
changes. Download Inter (https://github.com/rsms/inter/releases), then::

    uv run --with fonttools --with uharfbuzz python tools/generate_inter.py \\
        ~/Downloads/Inter/extras/ttf/Inter-ExtraBold.ttf
    uv run ruff format scraper/app/inter.py

The formatting pass is what keeps the generated file in the project's style, so
regenerating it produces no gratuitous diff.

Usage:
    generate_inter.py <font.ttf> [--output <path>]
"""

import argparse
import itertools
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "scraper" / "app" / "inter.py"

# Every character a badge can show: the digits and separators a follower count
# is built from, the em dash standing in for an unavailable count, and the
# capitals and space the platform-name variants spell their label with.
CHARS = "0123456789.,— " + "".join(chr(code) for code in range(65, 91))

HEADER = '''"""Inter ExtraBold outlines and metrics — generated, do not edit by hand.

Badges draw their text as these outlines instead of as SVG ``<text>``. An SVG
embedded with ``<img>`` can neither inherit the host page's fonts nor load one
of its own in every renderer, so a badge set in ``font-family: Inter`` really
renders in whatever the viewer has — and a fallback's metrics are not the ones
the badge was laid out with, which leaves the logo at the wrong distance from
the count. Outlines render identically everywhere, at the cost of the text no
longer being text (the badges carry ``<title>`` and ``aria-label`` for that).

Everything here is in font units; divide by :data:`UNITS_PER_EM` for ems.

Regenerate with ``tools/generate_inter.py`` — see that script for the command.

Inter is by Rasmus Andersson, under the SIL Open Font License 1.1
(https://github.com/rsms/inter).
"""
'''


def _fmt_dict(name: str, annotation: str, entries: dict, doc: str) -> str:
    """Return a formatted module-level dict assignment with a docstring."""
    lines = [f"{name}: {annotation} = {{"]
    lines += [f"    {key!r}: {value!r}," for key, value in entries.items()]
    lines += ["}", f'"""{doc}"""', ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font", type=Path, help="Path to Inter-ExtraBold.ttf")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    font = TTFont(args.font)
    upm = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    glyphs = font.getGlyphSet()
    cap_height = font["OS/2"].sCapHeight

    # Advances and outlines come from the font tables; kerning is measured by
    # shaping each pair through HarfBuzz, so it reflects what a browser applies
    # (GPOS, not just the legacy ``kern`` table).
    blob = hb.Blob.from_file_path(str(args.font))
    hb_font = hb.Font(hb.Face(blob))

    def shaped(text: str) -> int:
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(hb_font, buf, {})
        return sum(pos.x_advance for pos in buf.glyph_positions)

    advance = {char: glyphs[cmap[ord(char)]].width for char in CHARS}

    kern = {}
    for first, second in itertools.product(CHARS, repeat=2):
        delta = shaped(first + second) - advance[first] - advance[second]
        if delta:
            kern[first + second] = delta

    outlines = {}
    for char in CHARS:
        pen = SVGPathPen(glyphs, ntos=lambda value: str(round(value)))
        glyphs[cmap[ord(char)]].draw(pen)
        if commands := pen.getCommands():
            outlines[char] = commands

    parts = [
        HEADER,
        f"UNITS_PER_EM = {upm}\n"
        '"""Font units per em; the scale every measurement here is in."""\n',
        f"CAP_HEIGHT = {cap_height}\n"
        '"""Height of the capitals and digits, which have no ascenders or\n'
        'descenders — so it is the full height of a line of badge text."""\n',
        _fmt_dict(
            "ADVANCE",
            "dict[str, int]",
            advance,
            "How far the pen moves after drawing each character.",
        ),
        _fmt_dict(
            "KERN",
            "dict[str, int]",
            kern,
            "How much closer Inter sets each pair of characters than their\n"
            "advances alone would put them. Always negative here, bar a pair\n"
            "or two the font pushes apart.",
        ),
        _fmt_dict(
            "OUTLINES",
            "dict[str, str]",
            outlines,
            "SVG path data per character, drawn from an origin on the baseline\n"
            "and, like any font, with y pointing up — so a renderer needs to\n"
            "flip it. The space has no outline and is absent.",
        ),
    ]
    args.output.write_text("\n".join(parts), encoding="utf-8")

    biggest = max(outlines.values(), key=len)
    print(  # noqa: T201 — a hand-run generator, not the scraper
        f"Wrote {args.output.relative_to(REPO_ROOT)}: {len(outlines)} outlines, "
        f"{len(kern)} kern pairs, {len(advance)} advances "
        f"({sum(len(v) for v in outlines.values()) / 1024:.1f} KiB of path data, "
        f"largest glyph {len(biggest)} B)."
    )


if __name__ == "__main__":
    main()
