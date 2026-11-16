"""Таблица стран для Mini App из countries.py: python tools/gen_countries.py

Бот и витрина берут страны из одного места; флаги для новых стран
докачиваются с flagcdn.com в webapp/flags/.
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import countries  # noqa: E402

table = {c3: [v[0], v[1]] for c3, v in countries.COUNTRIES.items()}
regions = {k: " ".join(v) for k, v in countries.REGIONS.items()}
(ROOT / "webapp" / "countries.js").write_text(
    "// Сгенерировано tools/gen_countries.py из countries.py — не править руками.\n"
    f"window.NUM_COUNTRIES = {json.dumps(table, ensure_ascii=False)};\n"
    f"window.NUM_REGIONS = {json.dumps(regions, ensure_ascii=False)};\n", encoding="utf-8")
got = 0
for iso2, _ in table.values():
    f = ROOT / "webapp" / "flags" / f"{iso2.lower()}.svg"
    if not f.exists():
        with urllib.request.urlopen(f"https://flagcdn.com/{iso2.lower()}.svg", timeout=20) as r:
            f.write_bytes(r.read())
        got += 1
print(f"стран {len(table)}, регионов {len(regions)}, докачано флагов {got}")
