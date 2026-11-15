#!/usr/bin/env python3
"""Regenerate the header logo and favicons in static/ from the sources in logos/.

Run by hand when the logo changes: .venv/bin/python tools/make_logos.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
WIDE = ROOT / "logos/steve sickels phototography logo white bg w text large and gray-01.png"
STATIC = ROOT / "static"
HEADER_H = 53            # CSS px; images are made at 3x
DARK_TEXT = (200, 200, 195)   # lettering in dark mode

TEXT = (109, 110, 113)       # the logo's gray lettering
# The wide logo's squares, in source pixels after cropping to the artwork
# (measured from the PNG). Drawn as solid shapes so they stay opaque on dark.
WIDE_RECTS = [((0, 0, 921, 959), "#b0c4c0"), ((951, 0, 1517, 560), "#d2a84b"),
              ((1168, 589, 1517, 959), "#d1682e"), ((951, 774, 1141, 959), "#52678d")]
TEXT_X = 1600                # lettering starts right of here


def wide_logo(src: Image.Image, text_rgb, height: int) -> Image.Image:
    """Squares as solid rects + lettering as alpha (exact against white), then scaled."""
    gray = src.convert("L").crop((TEXT_X, 0, src.width, src.height))
    alpha = gray.point(lambda v: max(0, min(255, round((255 - v) * 255 / (255 - TEXT[1])))))
    out = Image.new("RGBA", src.size, text_rgb + (0,))
    text = Image.new("RGBA", gray.size, text_rgb + (255,)); text.putalpha(alpha)
    out.paste(text, (TEXT_X, 0))
    d = ImageDraw.Draw(out)
    for (x0, y0, x1, y1), c in WIDE_RECTS:
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=c)
    return out.resize((round(src.width * height / src.height), height), Image.LANCZOS)


def main():
    wide = Image.open(WIDE).convert("RGB")
    box = Image.eval(wide, lambda v: 255 - v).point(lambda v: 255 if v > 20 else 0).getbbox()
    wide = wide.crop(box)
    (STATIC / "img").mkdir(exist_ok=True)
    light = wide_logo(wide, TEXT, HEADER_H * 3)
    small = lambda im: im.quantize(64, method=Image.Quantize.FASTOCTREE)   # ~1/3 the bytes
    small(light).save(STATIC / "img/logo.png", optimize=True)
    small(wide_logo(wide, DARK_TEXT, HEADER_H * 3)).save(STATIC / "img/logo-dark.png", optimize=True)
    print("logo", light.size)

    # Favicons: draw the square mark crisply at each size from its geometry
    # (measured from "logo white bg Square.tif", a 242 px canvas).
    rects = [((1, 1, 141, 143), "#d2a84b"), ((148, 1, 241, 89), "#d1682e"),
             ((194, 95, 241, 143), "#52678d"), ((1, 150, 241, 242), "#b0c4c0")]
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 242 242">']
    svg += [f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="{c}"/>' for (x0, y0, x1, y1), c in rects]
    (STATIC / "favicon.svg").write_text("".join(svg) + "</svg>\n")

    def mark(size, bg=None):
        s = 8  # supersample
        im = Image.new("RGBA", (242 * s, 242 * s), bg or (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for (x0, y0, x1, y1), c in rects:
            d.rectangle((x0 * s, y0 * s, x1 * s - 1, y1 * s - 1), fill=c)
        return im.resize((size, size), Image.LANCZOS)
    (STATIC / "root").mkdir(exist_ok=True)
    mark(48).save(STATIC / "root/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    # iOS doesn't do transparency: white background with a small margin.
    touch = Image.new("RGBA", (180, 180), "white"); touch.alpha_composite(mark(150), (15, 15))
    touch.convert("RGB").save(STATIC / "root/apple-touch-icon.png", optimize=True)

if __name__ == "__main__":
    main()
