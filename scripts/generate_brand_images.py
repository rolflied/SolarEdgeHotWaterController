#!/usr/bin/env python3
"""
Generate the brand images for the SolarEdge Hot Water Controller integration.

Home Assistant 2026.3 and newer picks up brand images from the integration's
own ``brand/`` folder, so the icon shown in Settings → Devices & services
ships with the repository instead of coming from the brands CDN.

Usage:
    pip install pillow
    python3 scripts/generate_brand_images.py

The rendered PNGs are written to custom_components/solaredge_hwc/brand/.
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "custom_components",
    "solaredge_hwc",
    "brand",
)

# Supersampling factor: everything is drawn large and scaled down for smooth edges
SS = 4

# Colours
SUN_TOP = (255, 196, 61)      # warm amber, top left of the gradient
SUN_BOTTOM = (229, 66, 42)    # deep orange-red, bottom right
DROP = (255, 255, 255)
BOLT = (226, 74, 40)
TEXT_DARK = (28, 33, 40)
TEXT_DARK_MUTED = (98, 110, 124)
TEXT_LIGHT = (245, 247, 250)
TEXT_LIGHT_MUTED = (168, 178, 190)

FONT_CANDIDATES_BOLD = (
    "/mnt/skills/examples/canvas-design/canvas-fonts/WorkSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)
FONT_CANDIDATES_REGULAR = (
    "/mnt/skills/examples/canvas-design/canvas-fonts/WorkSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _font(candidates: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    """Return the first available font from the candidate list."""
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise SystemExit(f"None of these fonts were found: {candidates}")


def _diagonal_gradient(size: int, start, end) -> Image.Image:
    """Return a square image with a diagonal (top-left → bottom-right) gradient."""
    gradient = Image.new("RGB", (size, size))
    pixels = gradient.load()
    for y in range(size):
        for x in range(size):
            # 0 at the top-left corner, 1 at the bottom-right corner
            t = (x + y) / (2 * (size - 1))
            pixels[x, y] = tuple(
                round(start[i] + (end[i] - start[i]) * t) for i in range(3)
            )
    return gradient


def _droplet_polygon(cx: float, cy: float, r: float, tip_y: float) -> list[tuple[float, float]]:
    """
    Build a teardrop outline: a circle of radius *r* around (cx, cy) with a
    tip at (cx, tip_y), joined by the two tangents from the tip to the circle.
    """
    d = cy - tip_y
    # Tangent points as seen from the tip (image coordinates, y grows downwards)
    tangent_dx = r * math.sqrt(d * d - r * r) / d
    tangent_dy = -(r * r) / d

    a_right = math.atan2(tangent_dy, tangent_dx)
    a_left = math.atan2(tangent_dy, -tangent_dx)
    if a_left < a_right:
        a_left += 2 * math.pi

    points = [(cx, tip_y), (cx + tangent_dx, cy + tangent_dy)]
    steps = 180
    for i in range(steps + 1):
        angle = a_right + (a_left - a_right) * i / steps
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def _bolt_polygon(cx: float, cy: float, width: float, height: float) -> list[tuple[float, float]]:
    """Build a lightning bolt centred on (cx, cy)."""
    shape = [
        (0.60, 0.00),
        (0.14, 0.55),
        (0.42, 0.55),
        (0.34, 1.00),
        (0.86, 0.42),
        (0.55, 0.42),
    ]
    left = cx - width / 2
    top = cy - height / 2
    return [(left + x * width, top + y * height) for x, y in shape]


def render_icon(size: int) -> Image.Image:
    """Render the square app icon: a water drop with a bolt on a sunny ground."""
    s = size * SS

    icon = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Rounded square background with a warm gradient
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.225), fill=255)
    icon.paste(_diagonal_gradient(s, SUN_TOP, SUN_BOTTOM).convert("RGBA"), (0, 0), mask)

    draw = ImageDraw.Draw(icon)

    # Water drop
    cx, cy, r = s * 0.5, s * 0.605, s * 0.243
    draw.polygon(_droplet_polygon(cx, cy, r, s * 0.135), fill=DROP)

    # Lightning bolt inside the drop: the water is heated electrically
    draw.polygon(_bolt_polygon(cx, cy + s * 0.005, s * 0.225, s * 0.335), fill=BOLT)

    return icon.resize((size, size), Image.LANCZOS)


def render_logo(width: int, height: int, dark: bool) -> Image.Image:
    """Render the landscape logo: the icon plus the integration name."""
    s_w, s_h = width * SS, height * SS
    logo = Image.new("RGBA", (s_w, s_h), (0, 0, 0, 0))

    glyph_size = int(s_h * 0.78)
    glyph = render_icon(glyph_size)
    glyph_x = int(s_h * 0.11)
    logo.alpha_composite(glyph, (glyph_x, (s_h - glyph_size) // 2))

    draw = ImageDraw.Draw(logo)
    title_font = _font(FONT_CANDIDATES_BOLD, int(s_h * 0.30))
    subtitle_font = _font(FONT_CANDIDATES_REGULAR, int(s_h * 0.175))

    text_x = glyph_x + glyph_size + int(s_h * 0.20)
    draw.text(
        (text_x, s_h * 0.30),
        "SolarEdge HWC",
        font=title_font,
        fill=TEXT_LIGHT if dark else TEXT_DARK,
        anchor="lm",
    )
    draw.text(
        (text_x, s_h * 0.665),
        "Hot Water Controller",
        font=subtitle_font,
        fill=TEXT_LIGHT_MUTED if dark else TEXT_DARK_MUTED,
        anchor="lm",
    )

    return logo.resize((width, height), Image.LANCZOS)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    images = {
        "icon.png": render_icon(256),
        "icon@2x.png": render_icon(512),
        "logo.png": render_logo(640, 160, dark=False),
        "logo@2x.png": render_logo(1280, 320, dark=False),
        "dark_logo.png": render_logo(640, 160, dark=True),
        "dark_logo@2x.png": render_logo(1280, 320, dark=True),
    }

    for name, image in images.items():
        path = os.path.join(OUT_DIR, name)
        image.save(path, "PNG", optimize=True)
        print(f"{path}  {image.width}x{image.height}")


if __name__ == "__main__":
    main()
