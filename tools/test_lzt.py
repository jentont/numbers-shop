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

    # покупка: retry_request повторяется, 403 трижды подряд ставит покупки на паузу
    tries = {"n": 0}

    async def buy_call(method, path, params=None, json=None):
        if path.endswith("/fast-buy"):
            tries["n"] += 1
            if tries["n"] < 3:
                raise lzt.LztError("POST fast-buy → 400: retry_request")
            return {"item": {"item_id": 1, "loginData": {"login": "79990001122", "password": "pw"}, "rub_price": 20}}
        return await fake_call(method, path, params, json)

    lzt._call = buy_call  # noqa: SLF001
    real_sleep = asyncio.sleep

    async def no_sleep(*_):
        await real_sleep(0)

    asyncio.sleep = no_sleep
    got = await lzt.buy(1, 20)
    check("retry_request повторяется до успеха", tries["n"] == 3 and got["phone"] == "+79990001122")

    import db
    await db.touch_user(50, "B", "")
    await db.accept_terms(50)
    shop.LZT_STATE.update(buy_paused=False, buy_fails=0)

    # 1) первый лот мёртвый — бот сам покупает похожий из витрины, деньги не возвращаются
    bought = []

    async def dead_then_ok(item_id, cost):
        if not bought and item_id == 101:
            bought.append("dead")
            raise lzt.LztError("POST /101/fast-buy → 403: Сессия недействительна (произведен выход или аккаунт заблокирован)")
        bought.append(item_id)
        return {"phone": "+79991112233", "password": "", "cost": cost, "raw": {}}

    lzt.buy = dead_then_ok
    oid = await db.create_order(50, "live", 101, "RUS", 2000, 5000)
    await shop._fulfil(oid, 101, 20)  # noqa: SLF001
    o = await db.get_order(oid)
    check("мёртвый лот заменён похожим, заказ выдан", o["status"] == "done" and o["item_id"] != 101)
    check("мёртвый лот убран из витрины", all(x["id"] != 101 for x in shop.SNAP.get("RUS", (0, []))[1]))
    check("отказы по лотам не ставят покупки на паузу", not shop.LZT_STATE["buy_paused"])

    # 2) замены дороже оплаченного не берём — возврат, мы не в минусе
    async def always_dead(item_id, cost):
        raise lzt.LztError("POST /x/fast-buy → 403: У Вас нет прав для этого действия.")

    lzt.buy = always_dead
    bal = (await db.get_user(50))["kop"]
    oid = await db.create_order(50, "live", 201, "RUS", 1000, 1200)
    await shop._fulfil(oid, 201, 10)  # noqa: SLF001
    check("подходящей замены нет — заказ возвращён", (await db.get_order(oid))["status"] == "refunded"
          and (await db.get_user(50))["kop"] == bal + 1200)

    # 3) токен не принимается — после 3 таких отказов покупки на паузе
    async def bad_token(item_id, cost):
        raise lzt.LztError("POST /x/fast-buy → 401: Invalid or expired access token.")

    lzt.buy = bad_token
    for i in range(3):
        oid = await db.create_order(50, "live", 900 + i, "RUS", 1000, 1200)
        await shop._fulfil(oid, 900 + i, 10)  # noqa: SLF001
    check("3 отказа из-за токена — покупки на паузе", shop.LZT_STATE["buy_paused"])
    try:
        await shop.guard(50)
        paused = False
    except shop.ShopError as e:
        paused = e.code == "buy_paused"
    check("на паузе новые покупки не начинаются (деньги не списываются)", paused)
    asyncio.sleep = real_sleep

    # продавцы: чёрный список, новички, «восстановители», автобан по жалобам
    import config
    norm = lambda sid, name, sold, rest, banned=0: lzt.normalize({  # noqa: E731
        "item_id": sid, "telegram_country": "RU", "price": 20,
        "seller": {"user_id": sid, "username": name, "sold_items_count": sold, "restore_percents": rest,
                   "is_banned": banned}})
    check("AccPoint из чёрного списка не продаётся", not lzt.seller_ok(norm(1, "AccPoint", 35796, 0)))
    check("новичок (5 продаж) не продаётся", not lzt.seller_ok(norm(2, "newbie", 5, 0)))
    check("продавец с 40% восстановлений не продаётся", not lzt.seller_ok(norm(3, "thief", 900, 40)))
    check("забаненный продавец не продаётся", not lzt.seller_ok(norm(4, "ban", 900, 0, 1)))
    good = norm(5, "goodshop", 900, 2)
    check("нормальный продавец продаётся", lzt.seller_ok(good))
    for _ in range(config.SELLER_STRIKES):
        await shop.seller_strike({"seller": "goodshop", "seller_id": 5})
    check(f"{config.SELLER_STRIKES} нерабочих аккаунта — продавец сам попал в чёрный список",
          not lzt.seller_ok(good) and "goodshop" in config.SELLER_BLACKLIST)
    await shop.seller_ban("goodshop", on=False)
    check("/seller_unban возвращает продавца", lzt.seller_ok(good))

    # деньги на LZT: меньше, чем на балансах покупателей — сигнал админу
    notes = []

    async def fake_note(text, key=""):
        notes.append((key, text))

    real_note = shop._admin_note  # noqa: SLF001
    shop._admin_note = fake_note  # noqa: SLF001
    real_balance = lzt.balance

    async def low_balance():
        return 100.0

    lzt.balance = low_balance
    config.RESERVE_SIZE = 0
    await db.run("UPDATE users SET kop=0")
    await db.add_kop(50, 35000, "admin")            # у покупателя 350 ₽
    info = await shop.check_lzt_funds()
    check("на LZT 100 ₽, на балансах 350 ₽ — не хватает 250 ₽", info and round(info["short"]) == 250)
    check("админу пришёл сигнал «На LZT мало денег»", any(k == "lzt_funds" and "250" in t for k, t in notes))

    async def rich():
        return 1000.0

    lzt.balance = rich
    notes.clear()
    info = await shop.check_lzt_funds()
    check("денег хватает — сигнала нет", info["short"] == 0 and not notes)
    lzt.balance = real_balance
    shop._admin_note = real_note  # noqa: SLF001

    # код входа: в любом виде ответа, самый свежий
    P = lzt.parse_login_code
    check("код из списка codes — самый свежий",
          P({"codes": [{"code": "12345", "date": 1}, {"code": "67890", "date": 5}]})["code"] == "67890")
    check("код из текста сообщения Telegram",
          P({"messages": [{"text": "Login code: 48213. Do not give this code", "date": 9}]})["code"] == "48213")
    check("номер телефона и цены за код не принимаются",
          P({"item": {"phone": "+15551234567", "note": "price 12345.50"}}) is None)
    check("пустой ответ — кода нет", P({"codes": []}) is None)

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
