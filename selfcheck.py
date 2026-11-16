"""Самопроверка денежной логики: python selfcheck.py

Работает на отдельной временной базе и демо-LZT, ничего не покупает и
никому не пишет. Проверяет главное правило — мы всегда в плюсе — и что
ни одна гонка не даёт денег из воздуха.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ["LZT_DEMO"] = "1"
os.environ["CHANNEL"] = ""
os.environ["RESERVE_SIZE"] = "0"
os.environ["MAX_PER_DAY_NEW"] = "50"
TMP = Path(tempfile.mkdtemp()) / "check.db"
os.environ["DB_PATH"] = str(TMP)
sys.path.insert(0, str(Path(__file__).parent))

import config  # noqa: E402
import crypto  # noqa: E402
import db  # noqa: E402
import lzt  # noqa: E402
import shop  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILS.append(name)


async def bal(uid: int) -> int:
    return int((await db.get_user(uid))["kop"])


async def main() -> None:
    await db.init(TMP)
    print("Цены")
    for cost in (0.5, 8, 15, 28.4, 99.99, 1000):
        p = shop.price_kop(cost)
        check(f"цена {cost} ₽ → {p / 100:.0f} ₽ ≥ закупка + {config.MIN_MARGIN_RUB:.0f} ₽", p >= (cost + config.MIN_MARGIN_RUB) * 100)
        check(f"цена {cost} ₽ ≥ +{config.MARKUP:.0%}", p >= cost * (1 + config.MARKUP) * 100)
        for promo in (10, 50):
            check(f"акция −{promo}% на {cost} ₽ не ниже закупки + 1 ₽", shop.price_kop(cost, promo) >= (cost + 1) * 100)
    check("звёзды дороже ×2", shop.stars_for(10000) >= 100 / config.STAR_RUB * 2)

    print("Баланс")
    await db.touch_user(1, "A", "alice")
    await db.touch_user(2, "B", "bob")
    await db.add_kop(1, 10000, "admin")
    res = await asyncio.gather(*[db.take_kop(1, 3000, "buy") for _ in range(10)])
    check("10 одновременных списаний по 30 ₽ при 100 ₽ — прошло ровно 3", sum(res) == 3)
    check("баланс не ушёл в минус", await bal(1) == 1000)

    print("Пополнение")
    inv = await db.create_invoice(1, "cryptobot", 5000)
    r = await asyncio.gather(*[db.pay_invoice(inv) for _ in range(5)])
    check("счёт зачислен ровно один раз", sum(1 for x in r if x) == 1 and await bal(1) == 6000)
    check("xRocket: totalActivations без статуса paid — не оплата",
          not crypto._xrocket_paid({"status": "active", "totalActivations": 1, "activationsLeft": 1}))  # noqa: SLF001
    check("xRocket: paid — оплата", crypto._xrocket_paid({"status": "paid", "totalActivations": 1, "activationsLeft": 0}))  # noqa: SLF001

    print("Перевод и промокод")
    check("перевод больше баланса не проходит", not await db.transfer(1, 2, 999_999))
    check("перевод 20 ₽", await db.transfer(1, 2, 2000) and await bal(1) == 4000 and await bal(2) == 2000)
    await db.create_promo("SALE", 500, 2)
    got = await asyncio.gather(*[db.use_promo(1, "sale") for _ in range(5)])
    check("промокод одному человеку — один раз", sum(1 for g in got if isinstance(g, int)) == 1)
    await db.use_promo(2, "SALE")
    await db.touch_user(3, "C", "")
    check("лимит активаций соблюдён", await db.use_promo(3, "SALE") == "promo_bad")

    print("Защита от злоупотреблений")
    await db.add_kop(1, 100_000, "admin")
    lot0 = (await lzt.search(country="RUS"))[5]
    try:
        await shop.buy_lot(1, lot0["id"], 0)
        check("без принятых условий покупка запрещена", False)
    except shop.ShopError as e:
        check("без принятых условий покупка запрещена", e.code == "terms")
    for uid in (1, 2, 3):
        await db.accept_terms(uid)
    await db.set_ban(3, "спам")
    await db.add_kop(3, 100_000, "admin")
    try:
        await shop.buy_lot(3, lot0["id"], 0)
        check("забаненному покупка запрещена", False)
    except shop.ShopError as e:
        check("забаненному покупка запрещена", e.code == "banned")
    # Лимит по умолчанию выключен (0). Включаем 1 в сутки и «покупаем» один раз.
    old_limit = config.MAX_PER_DAY_NEW
    config.MAX_PER_DAY_NEW = 1
    tmp = await db.create_order(1, "live", 1, "RUS", 100, 200)
    try:
        await shop.buy_lot(1, lot0["id"], 0)
        check("включённый суточный лимит соблюдается", False)
    except shop.ShopError as e:
        check("включённый суточный лимит соблюдается", e.code == "day_limit")
    await db.run("UPDATE users SET trusted=1 WHERE id=1")
    try:
        await shop.guard(1)
        check("доверенному лимит не мешает", True)
    except shop.ShopError:
        check("доверенному лимит не мешает", False)
    await db.run("UPDATE users SET trusted=0 WHERE id=1")
    await db.run("DELETE FROM orders WHERE id=?", (tmp,))
    config.MAX_PER_DAY_NEW = 0
    await shop.guard(1)
    check("лимит 0 = без лимита", True)
    config.MAX_PER_DAY_NEW = old_limit
    check("ни одна запрещённая покупка не списала деньги", await bal(3) == 100_000)

    print("Покупка под заказ")
    lots = await lzt.search(country="RUS")
    lot = lots[0]
    before = await bal(1)
    orig_buy = lzt.buy

    async def fail_buy(*a, **k):
        raise lzt.LztError("тест: лот уже купили")

    lzt.buy = fail_buy
    o = await shop.buy_lot(1, lot["id"], 0)
    await asyncio.sleep(0.2)
    o = await db.get_order(o["id"])
    check("LZT отказал → заказ возвращён", o["status"] == "refunded")
    check("LZT отказал → деньги вернулись полностью", await bal(1) == before)
    lzt.buy = orig_buy

    lot = lots[1]
    o = await shop.buy_lot(1, lot["id"], 0)
    try:
        await shop.buy_lot(1, lot["id"], 0)
        check("тот же лот второй раз не продаётся", False)
    except shop.ShopError as e:
        check("тот же лот второй раз не продаётся", e.code == "gone")
    for _ in range(40):
        if (await db.get_order(o["id"]))["status"] != "pending":
            break
        await asyncio.sleep(0.1)
    o = await db.get_order(o["id"])
    check("покупка выполнена и в плюсе", o["status"] == "done" and o["price_kop"] > o["cost_kop"])

    print("Гарантия")
    orig = lzt.check_owned

    async def invalid(_):
        return "invalid"

    lzt.check_owned = invalid
    before = await bal(1)
    r1 = await shop.report(1, o["id"])
    try:
        await shop.report(1, o["id"])
        twice = True
    except shop.ShopError:
        twice = False
    check("невалидный → возврат цены покупателю", r1["result"] == "refunded" and await bal(1) == before + o["price_kop"])
    check("повторная жалоба не возвращает второй раз", not twice and await bal(1) == before + o["price_kop"])
    lzt.check_owned = orig

    print("Резерв")
    await db.reserve_add(111, "RUS", 2000, "+79990000001", "", {})
    await db.reserve_add(112, "RUS", 2000, "+79990000002", "", {})
    await db.touch_user(5, "E", "")
    await db.accept_terms(5)
    await db.add_kop(5, shop.price_kop(20), "admin")
    res = await asyncio.gather(*[shop.buy_instant(5, "RUS") for _ in range(3)], return_exceptions=True)
    okc = sum(1 for x in res if isinstance(x, dict))
    check("денег на один — продан ровно один из резерва", okc == 1 and await bal(5) == 0)
    left = await db.reserve_ready("RUS")
    check("второй аккаунт вернулся в резерв", len(left) == 1)

    print("Рефералы")
    await db.touch_user(10, "Ref", "")
    for i in range(100, 100 + config.REF_GOAL):
        await db.touch_user(i, f"f{i}", "")
        await db.set_ref(i, 10)
    check("сам себя не пригласить", not await db.set_ref(10, 10))
    res = await asyncio.gather(*[shop.ref_claim(10) for _ in range(3)], return_exceptions=True)
    okc = sum(1 for x in res if isinstance(x, dict))
    check(f"{config.REF_GOAL} друзей → ровно один приз", okc == 1)
    o = [x for x in res if isinstance(x, dict)][0]
    row = await db.get_order(o["id"])
    check(f"приз не дороже {config.REF_PRIZE_MAX:.0f} ₽", row["cost_kop"] <= config.REF_PRIZE_MAX * 100)

    await db.close()
    await lzt.close()
    print()
    print("ВСЁ В ПОРЯДКЕ" if not FAILS else f"ОШИБКИ: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
