"""«Хакерский» прогон: python tools/fuzz.py

Ведёт себя как злоумышленник: шлёт API мусор, гигантские и «бесконечные»
числа, чужие ID, подделанную подпись, параллельные списания, купить лот не
из витрины, подделанные кнопки текстовой версии. Цель — ни одного 500,
ни одной копейки из воздуха, ни одного чужого номера.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.update(LZT_DEMO="1", CHANNEL="", RESERVE_SIZE="0", BOT_TOKEN="1:TEST", WEBAPP_URL="", DEV_AUTH="1",
                  DB_PATH=str(Path(tempfile.mkdtemp()) / "f.db"))
sys.path.insert(0, str(ROOT))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402
import shop  # noqa: E402
import web  # noqa: E402

FAILS: list[str] = []
GARBAGE = [None, "", "abc", -1, -10**30, 10**30, 1e308, "1e999", "inf", "-inf", "nan", "NaN", [], {}, True,
           "0x10", " 5 ", "5;DROP TABLE users", "' OR 1=1 --", "<script>alert(1)</script>", 3.7, "9" * 400]


def check(name: str, cond: bool) -> None:
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILS.append(name)


async def main() -> None:
    await db.init()
    client = TestClient(TestServer(web.app()))
    await client.start_server()
    H = lambda uid: {"X-Dev": str(uid), "Content-Type": "application/json"}  # noqa: E731

    async def call(method, path, uid=1, body=None, raw=None):
        kw = {"headers": H(uid)}
        if raw is not None:
            kw["data"] = raw
        elif body is not None:
            kw["data"] = json.dumps(body)
        r = await client.request(method, path, **kw)
        return r.status, await r.text()

    for uid in (1, 2, 9):
        await call("GET", "/api/me", uid)
        await db.accept_terms(uid)
    await db.add_kop(1, 10_000, "admin")
    for c3 in ("RUS", "USA"):
        await shop.refresh_country(c3)

    print("Мусор во все ручки")
    five = 0
    posts = ["/api/buy", "/api/code", "/api/report", "/api/topup", "/api/transfer", "/api/promo", "/api/lang",
             "/api/giveaway/join", "/api/ref/claim", "/api/accept", "/api/tour"]
    fields = ["item_id", "price", "order", "rub", "to", "code", "provider", "lang", "instant"]
    for path in posts:
        for _ in range(40):
            body = {f: random.choice(GARBAGE) for f in random.sample(fields, random.randint(0, len(fields)))}
            st, _ = await call("POST", path, uid=9, body=body)
            five += st >= 500
        for raw in ("not json", "[1,2]", '"str"', "null", "{" * 1000):
            st, _ = await call("POST", path, uid=9, raw=raw)
            five += st >= 500
    for path in ["/api/order/99999999999999999999999", "/api/invoice/1e9", "/api/order/-1", "/api/history?page=-5",
                 "/api/history?page=abc", "/api/history?page=99999999999999999999", "/api/lots?country=../../etc",
                 "/api/lots?country=RUS&pmin=nan&pmax=inf", "/api/lots?country=' OR 1=1", "/terms?lang=../../x",
                 "/privacy?lang=<script>", "/static/../config.py", "/static/..%2f..%2fconfig.py", "/static/legal/../../.env"]:
        st, text = await call("GET", path, uid=9)
        five += st >= 500
        if "BOT_TOKEN" in text or "LZT_TOKEN" in text:
            check(f"утечка секретов через {path}", False)
    check("ни одного 500 на мусоре", five == 0)
    check("баланс не изменился от мусора", (await db.get_user(1))["kop"] == 10_000)

    print("Подпись Telegram")
    r = await client.get("/api/me", headers={"X-Init-Data": "user=%7B%22id%22%3A1%7D&hash=deadbeef"})
    check("поддельная подпись → 401", r.status == 401)
    config.WEBAPP_URL = "https://shop.example"
    r = await client.get("/api/me", headers={"X-Dev": "1"})
    check("DEV-вход отключён, когда задан боевой адрес", r.status == 401)
    config.WEBAPP_URL = ""

    print("Покупка лота не из витрины")
    for fake in (1, 123456789, 9_000_000_000):
        st, text = await call("POST", "/api/buy", body={"item_id": fake, "price": 100})
        check(f"чужой item_id {fake} не покупается", st == 400 and "gone" in text)

    print("Чужие данные")
    lot = (await shop.lots("RUS", {}))[0]
    st, text = await call("POST", "/api/buy", body={"item_id": lot["id"], "price": lot["price"]})
    oid = json.loads(text)["order"]["id"]
    await asyncio.sleep(1.6)
    for path, body in (("/api/code", {"order": oid}), ("/api/report", {"order": oid})):
        st, _ = await call("POST", path, uid=2, body=body)
        check(f"{path}: чужой заказ недоступен", st == 400)
    st, _ = await call("GET", f"/api/order/{oid}", uid=2)
    check("чужой заказ не открывается", st == 404)

    print("Деньги из воздуха")
    before = (await db.get_user(1))["kop"]
    res = await asyncio.gather(*[call("POST", "/api/transfer", body={"to": "2", "rub": before / 100})
                                 for _ in range(15)])
    okc = sum(1 for st, _ in res if st == 200)
    tot = (await db.get_user(1))["kop"] + (await db.get_user(2))["kop"]
    check("15 параллельных переводов всего баланса — прошёл один", okc == 1)
    check("сумма балансов не выросла", tot == before)
    for bad in (-50, 0, 0.001, "1e400", "inf", float("nan")):
        st, _ = await call("POST", "/api/transfer", uid=2, body={"to": "1", "rub": bad})
        check(f"перевод {bad!r} отклонён", st == 400)
    st, _ = await call("POST", "/api/transfer", uid=2, body={"to": "2", "rub": 20})
    check("перевод себе отклонён", st == 400)

    print("Перебор промокодов")
    await db.create_promo("SECRET777", 10_000, 100)
    codes = [f"SECRET{i}" for i in range(20)] + ["SECRET777"]
    got = [await call("POST", "/api/promo", uid=2, body={"code": c}) for c in codes]
    check("после 10 попыток перебор останавливается", all("slow_down" in t for _, t in got[10:]))

    print("Счета")
    sts = [(await call("POST", "/api/topup", body={"provider": "stars", "rub": 100}))[0] for _ in range(8)]
    check("бесконечно плодить счета нельзя", sts.count(200) <= 5)

    print("Защита от флуда")
    sts = await asyncio.gather(*[call("GET", "/api/me", uid=3) for _ in range(200)])
    check("200 запросов за секунду → ограничение 429", any(st == 429 for st, _ in sts))

    print("XSS в имени")
    await db.touch_user(66, '<a href="https://evil">x</a>', "")
    w = await shop.who(66)
    check("имя экранируется в уведомлениях админу", "<a href" not in w)

    print("Возврат скрывает аккаунт")
    o = await db.get_order(oid)
    await db.run("UPDATE orders SET status='refunded' WHERE id=?", (oid,))
    v = await shop.order_view(await db.get_order(oid))
    check("после возврата номер и пароль скрыты", not v["phone"] and not v["password"])
    del o

    await client.close()
    await db.close()
    print()
    print("ВЗЛОМ НЕ УДАЛСЯ — ВСЁ В ПОРЯДКЕ" if not FAILS else f"НАЙДЕНО ПРОБЛЕМ: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
