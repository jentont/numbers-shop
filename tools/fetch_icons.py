"""Скачивает иконки Lucide (ISC) и собирает webapp/icons.js + tools/svg/*.svg.

    python tools/fetch_icons.py

Одни и те же глифы идут в витрину и в эмодзи-набор (tools/make_emoji.py).
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "svg"
VER = "0.460.0"

# наше имя → варианты имён в Lucide (первый найденный)
ICONS = {
    "phone": ["smartphone"], "sim": ["card-sim", "sim-card", "custom:sim"], "cart": ["shopping-cart"], "globe": ["globe"],
    "bolt": ["zap"], "gift": ["gift"], "card": ["credit-card"], "wallet": ["wallet"], "star": ["star"],
    "flame": ["flame"], "tag": ["tag"], "box": ["package"], "check": ["check"], "lock": ["lock"],
    "key": ["key-round", "key"], "book": ["book-open"], "chat": ["message-circle"], "crown": ["crown"],
    "user": ["user"], "users": ["users"], "down": ["arrow-down"], "sparkles": ["sparkles"],
    "rocket": ["rocket"], "clock": ["clock"], "hash": ["hash"], "plus": ["plus"], "back": ["arrow-left"],
    "chart": ["bar-chart-3", "chart-column"], "trophy": ["trophy"], "bell": ["bell"], "copy": ["copy"],
    "shield": ["shield-check"], "gem": ["gem"], "coin": ["coins"], "search": ["search"],
    "megaphone": ["megaphone"], "refund": ["undo-2"], "wave": ["hand"], "filter": ["sliders-horizontal"],
    "x": ["x"], "chevron": ["chevron-right"], "home": ["store"], "bag": ["shopping-bag"],
    "sort": ["arrow-up-down"], "eye": ["eye"], "percent": ["percent"], "truck": ["truck"],
    "history": ["history"], "info": ["info"], "external": ["external-link"], "lang": ["languages"],
    "send": ["send"], "dice": ["dices"], "calendar": ["calendar"], "ticket": ["ticket"],
}


#: Своих глифов нет в Lucide этой версии — рисуем в том же стиле (24×24, штрих 2).
CUSTOM = {
    "sim": '<path d="M7 2h7l5 5v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" />'
           ' <rect x="8.5" y="11" width="7" height="7" rx="1" /> <path d="M12 11v7" /> <path d="M8.5 14.5h7" />',
}
SVG_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">')


def fetch(name: str) -> str | None:
    if name.startswith("custom:"):
        return SVG_HEAD + CUSTOM[name[7:]] + "</svg>"
    url = f"https://unpkg.com/lucide-static@{VER}/icons/{name}.svg"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.read().decode()
    except Exception:  # noqa: BLE001
        return None


def inner(svg: str) -> str:
    body = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return re.sub(r"\s+", " ", body).strip()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    js = {}
    for ours, names in ICONS.items():
        svg = None
        for n in names:
            svg = fetch(n)
            if svg:
                break
        if not svg:
            print("нет иконки:", ours, names)
            continue
        (OUT / f"{ours}.svg").write_text(svg, encoding="utf-8")
        js[ours] = inner(svg)
    (ROOT / "webapp" / "icons.js").write_text(
        "// Иконки Lucide (ISC license), собраны tools/fetch_icons.py\n"
        f"window.ICONS = {json.dumps(js, ensure_ascii=False, indent=0)};\n", encoding="utf-8")
    print("иконок:", len(js))


if __name__ == "__main__":
    main()
