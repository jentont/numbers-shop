"""Поиск LZT на подставном ответе маркета: python tools/test_lzt.py"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.update(LZT_TOKEN="test", LZT_DEMO="0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import lzt  # noqa: E402

FAILS = []
CALLS = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILS.append(name)


def item(i, country, spam=0, origin="autoreg", price=20):
    return {"item_id": i, "telegram_country": country, "price": price, "telegram_spam_block": spam, "item_origin": origin}


async def fake_call(method, path, params=None, json=None):
    CALLS.append(dict(params or []))
    p = dict(params or [])
    if "spam" in p or "origin[]" in p:
        raise lzt.LztError("400: неизвестный фильтр")       # раньше это роняло весь каталог
    if p.get("country[]") == "RUS":
        return {"items": [], "hasNextPage": False}            # маркет ждёт RU, а не RUS
    if p.get("country[]") == "RU":
        return {"items": [item(1, "RU"), item(2, "RU", spam=1), item(3, "RU", origin="stealer"),
                          item(4, "Russia"), item(5, "KZ")], "hasNextPage": False}
    return {"items": [], "hasNextPage": False}


async def main():
    lzt._call = fake_call  # noqa: SLF001
    lots = await lzt.search("RUS", pages=1)
    ids = sorted(x["id"] for x in lots)
    check("фильтры спама и происхождения в маркет не отправляются", not any("spam" in c or "origin[]" in c for c in CALLS))
    check("формат страны сам переключился на ISO-2 (RU)", lzt.COUNTRY_FMT["fmt"] == "iso2")
    check("спамблок и stealer отфильтрованы у нас, чужая страна отброшена", ids == [1, 4])
    check("страна словом (Russia) распознана", any(x["id"] == 4 and x["country"] == "RUS" for x in lots))
    print("\nПОИСК LZT: ВСЁ В ПОРЯДКЕ" if not FAILS else f"\nОШИБКИ: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
