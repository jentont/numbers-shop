"""Поиск и обход LZT на подставных ответах маркета: python tools/test_lzt.py

Повторяет то, что показал боевой /lzt: страны в ответе двумя буквами (RU, MA),
фильтр страны понимает не RUS/RU, а один «третий» формат, страницы — через page.
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.update(LZT_TOKEN="test", LZT_DEMO="0", CRAWL_CHEAP_PAGES="5", CRAWL_NEW_PAGES="2")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lzt  # noqa: E402
import shop  # noqa: E402

FAILS = []
CALLS = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILS.append(name)


def item(i, country, spam=0, origin="autoreg", price=20):
    return {"item_id": i, "telegram_country": country, "price": price, "telegram_spam_block": spam, "item_origin": origin}


def page_items(page):
    base = page * 100
    return [item(base + 1, "RU"), item(base + 2, "MA"), item(base + 3, "IT", spam=1),
            item(base + 4, "PH", origin="stealer"), item(base + 5, "IN")]


async def fake_call(method, path, params=None, json=None):
    p = dict(params or [])
    CALLS.append(p)
    if "spam" in p or "origin[]" in p or "after" in p:
        raise lzt.LztError("400: такого параметра нет")
    if "country[]" in p:
        ok = p["country[]"] == "Russia"                        # маркет понимает только название
        return {"items": [item(7, "RU")] if ok else [], "totalItems": 1 if ok else 0, "hasNextPage": False}
    page = int(p.get("page", 1))
    return {"items": page_items(page), "totalItems": 999, "hasNextPage": page < 3}


async def main():
    lzt._call = fake_call  # noqa: SLF001
    found = await lzt.probe_country_format()
    check("формат страны подобран сам (Russia)", lzt.COUNTRY_FMT["fmt"] == "name" and found["name"] == 1)

    cheap = await lzt.crawl("price_to_up", 5)
    pages = [c.get("page") for c in CALLS if "page" in c and "country[]" not in c]
    check("страницы листаются параметром page и обход останавливается на последней", pages == [1, 2, 3])
    check("курсор after и фильтры спама/происхождения в маркет не уходят",
          not any("after" in c or "spam" in c or "origin[]" in c for c in CALLS))
    countries = sorted({x["country"] for x in cheap})
    check("спамблок и stealer отфильтрованы, страны распознаны (RU, MA, IN)", countries == ["IND", "MAR", "RUS"])

    shop._ingest(cheap)  # noqa: SLF001
    check("лоты разложены по странам в витрине, Марокко тоже", {"RUS", "MAR", "IND"} <= set(shop.SNAP))
    check("в витрине все 9 лотов трёх страниц", sum(len(v[1]) for v in shop.SNAP.values()) == 9)

    lots = await shop.lots("RUS", {})
    check("страна открывается: свои лоты + подгрузка по фильтру", {x["id"] for x in lots} >= {101, 7})

    lzt.COUNTRY_FMT.update(fmt="none")
    lzt._cache.clear()  # noqa: SLF001
    lots = await shop.lots("MAR", {})
    check("фильтр страны не работает — страна всё равно из общего обхода", len(lots) == 3)

    print("\nПОИСК LZT: ВСЁ В ПОРЯДКЕ" if not FAILS else f"\nОШИБКИ: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)


async def run():
    import db
    import tempfile
    await db.init(Path(tempfile.mkdtemp()) / "l.db")
    try:
        await main()
    finally:
        await db.close()


asyncio.run(run())
