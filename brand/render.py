"""Write the integration's brand images from brand/icon.svg and brand/logo.svg.

Home Assistant 2026.3 and later show custom_components/roommate/brand/icon.png in Settings
and HACS and logo.png on the integration page, with dark_logo.png on the dark theme. The
README shows dark_logo.png: its white wordmark reads on dark grounds and vanishes on white
ones, leaving the badge, since HACS renders the README without theme switching. The
wordmark is Fredoka Bold, shaped from the font in brand/fonts and outlined, so no renderer
needs the font installed. Run it as
`uv run --frozen --with resvg-py --with fonttools --with uharfbuzz python brand/render.py`.
"""

import io
import math
import re
import struct
from pathlib import Path

import resvg_py
import uharfbuzz
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "brand"
TARGET = ROOT / "custom_components/roommate/brand"
FONT = BRAND / "fonts/Fredoka[wdth,wght].ttf"
# Kerning and ligatures, as a browser would apply them.
FEATURES = {"kern": True, "liga": True}
# The wordmark's ink per file prefix. logo.svg carries the light one, dark_logo.png is pure
# white so it disappears on the white cards the README is shown on in light themes.
INKS = {"": None, "dark_": "#FFFFFF"}
WORDMARK = re.compile(
    r'<text x="([\d.]+)" y="([\d.]+)" font-family="Fredoka" font-size="([\d.]+)" '
    r'font-weight="(\d+)" letter-spacing="(-?[\d.]+)" fill="(#[0-9A-Fa-f]{6})">([a-z]+)</text>'
)


def _number(value):
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _outline(text, size, weight, tracking):
    """Return the wordmark as one path and the x where its ink ends."""
    font = TTFont(FONT)
    # Every axis at its default except the weight, so the width stays normal.
    axes = {axis.axisTag: axis.defaultValue for axis in font["fvar"].axes}
    axes["wght"] = weight
    instantiateVariableFont(font, axes, inplace=True)
    binary = io.BytesIO()
    font.save(binary)
    shaper = uharfbuzz.Font(uharfbuzz.Face(binary.getvalue()))
    buffer = uharfbuzz.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    uharfbuzz.shape(shaper, buffer, FEATURES)
    glyphs = font.getGlyphSet()
    names = font.getGlyphOrder()
    scale = size / font["head"].unitsPerEm
    path = SVGPathPen(glyphs, ntos=_number)
    bounds = BoundsPen(glyphs)
    x = 0.0
    for info, position in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True):
        offset = ((x + position.x_offset) * scale, -position.y_offset * scale)
        transform = (scale, 0, 0, -scale, *offset)
        glyph = glyphs[names[info.codepoint]]
        glyph.draw(TransformPen(path, transform))
        glyph.draw(TransformPen(bounds, transform))
        x += position.x_advance + tracking / scale
    return path.getCommands(), bounds.bounds[2]


def _logo(source, ink=None):
    """Return logo.svg with the wordmark outlined and trimmed to the text, and its width.

    The ink replaces the source's when given.
    """
    wordmark = WORDMARK.search(source)
    if wordmark is None:
        raise ValueError("brand/logo.svg has no wordmark to outline")
    x, y, size, weight, tracking = (float(value) for value in wordmark.groups()[:5])
    ink, text = ink or wordmark.group(6), wordmark.group(7)
    commands, end = _outline(text, size, int(weight), tracking)
    width = math.ceil(x + end)
    path = f'<path transform="translate({_number(x)} {_number(y)})" fill="{ink}" d="{commands}"/>'
    svg = source[: wordmark.start()] + path + source[wordmark.end() :]
    size = f'viewBox="0 0 {width} 256" width="{width}"'
    return re.sub(r'viewBox="0 0 \d+ 256" width="\d+"', size, svg), width


def _write(svg, path, zoom, expected):
    """Render the SVG at a zoom and check the PNG's pixel size, so a bad source can't ship."""
    png = resvg_py.svg_to_bytes(svg_string=svg, zoom=zoom)
    width, height = struct.unpack(">II", png[16:24])
    if (width, height) != expected:
        raise ValueError(f"{path.name} rendered at {width} by {height}, expected {expected}")
    path.write_bytes(png)


def main():
    icon = (BRAND / "icon.svg").read_text()
    _write(icon, TARGET / "icon.png", 0.5, (256, 256))
    _write(icon, TARGET / "icon@2x.png", 1, (512, 512))
    source = (BRAND / "logo.svg").read_text()
    for prefix, ink in INKS.items():
        logo, width = _logo(source, ink)
        _write(logo, TARGET / f"{prefix}logo.png", 1, (width, 256))
        _write(logo, TARGET / f"{prefix}logo@2x.png", 2, (width * 2, 512))
    print(f"Wrote the icon and logo into {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
