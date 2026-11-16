"""Генерирует картинки для набора кастомных эмодзи (assets/emoji/*.png).

Белая плитка со скруглёнными углами + чёрный Lucide-глиф. 100x100 RGBA.
Запуск: python tools/make_emoji.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SVG_DIR = ROOT / "tools" / "svg"
OUT = ROOT / "assets" / "emoji"
FONT = ROOT / "webapp" / "fonts" / "Unbounded-Black.ttf"

# MAP читаем из исходника emoji.py, не импортируя бота (config, aiogram)
_src = (ROOT / "emoji.py").read_text(encoding="utf-8")
_block = _src[_src.index("MAP = {"):]
_block = _block[:_block.index("\n}") + 2]
NAMES = re.findall(r'"([a-z_]+)"\s*:', _block)

SIZE = 100
SS = 4                     # суперсэмплинг
BIG = SIZE * SS
RADIUS = 24
BORDER = 1.25
FILL = (255, 255, 255, 255)
EDGE = (228, 228, 224, 255)   # #E4E4E0
INK = "#0B0B0C"
GLYPH = 0.58               # доля плитки под глиф
STROKE = 2.1               # в единицах 24-вьюбокса


def tile() -> Image.Image:
    im = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, BIG - 1, BIG - 1), radius=RADIUS * SS, fill=EDGE)
    b = BORDER * SS
    d.rounded_rectangle((b, b, BIG - 1 - b, BIG - 1 - b), radius=RADIUS * SS - b, fill=FILL)
    return im


def svg_inner(name: str) -> str:
    s = (SVG_DIR / f"{name}.svg").read_text(encoding="utf-8")
    return s[s.index(">", s.index("<svg")) + 1:s.rindex("</svg>")]


def render_glyphs(names: list[str]) -> dict[str, Image.Image]:
    px = round(BIG * GLYPH)
    cells = "".join(
        f'<div class="c" id="i_{n}"><svg xmlns="http://www.w3.org/2000/svg" width="{px}" height="{px}" '
        f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{STROKE}" '
        f'stroke-linecap="round" stroke-linejoin="round">{svg_inner(n)}</svg></div>'
        for n in names)
    html = (f"<!doctype html><html><head><style>html,body{{margin:0;background:transparent}}"
            f".c{{width:{px}px;height:{px}px;color:{INK};display:block}}svg{{display:block}}</style>"
            f"</head><body>{cells}</body></html>")
    out = {}
    with sync_playwright() as p:
        br = p.chromium.launch(channel="msedge")
        pg = br.new_page(viewport={"width": px, "height": px}, device_scale_factor=1)
        pg.set_content(html)
        for n in names:
            png = pg.locator(f"#i_{n}").screenshot(omit_background=True)
            out[n] = Image.open(io.BytesIO(png)).convert("RGBA")
        br.close()
    return out


def glyph_s() -> Image.Image:
    im = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(str(FONT), size=int(BIG * 0.52))
    l, t, r, b = d.textbbox((0, 0), "S", font=font)
    x = (BIG - (r - l)) / 2 - l
    y = (BIG - (b - t)) / 2 - t
    d.text((x, y), "S", font=font, fill=INK)
    return im


def finish(big: Image.Image, path: Path) -> None:
    small = big.resize((SIZE, SIZE), Image.LANCZOS)
    small.save(path, "PNG", optimize=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icons = [n for n in NAMES if n != "s"]
    missing = [n for n in icons if not (SVG_DIR / f"{n}.svg").exists()]
    if missing:
        sys.exit(f"нет svg: {missing}")
    glyphs = render_glyphs(icons)
    base = tile()
    for n in icons:
        im = base.copy()
        g = glyphs[n]
        im.alpha_composite(g, ((BIG - g.width) // 2, (BIG - g.height) // 2))
        finish(im, OUT / f"{n}.png")
    if "s" in NAMES:
        im = base.copy()
        im.alpha_composite(glyph_s())
        finish(im, OUT / "s.png")
    print(f"готово: {len(list(OUT.glob('*.png')))} png в {OUT}")


if __name__ == "__main__":
    main()
