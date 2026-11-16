"""Ядро магазина: цены, витрина, покупка, резерв, «завоз» и конкурс.

Правило бизнеса: мы всегда в плюсе.
* Цена = закупка LZT + 10 %, но не меньше закупки + MIN_MARGIN_RUB.
* Акция режет только нашу наценку, цена не опускается ниже закупки + 1 ₽.
* Покупка на LZT идёт с потолком цены = закупка, по которой мы назвали
  цену покупателю. Подорожал лот — LZT откажет, деньги вернутся.
* Конкурс тратит деньги, только если маржа за сутки покрывает приз.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import logging
import math
import random
import time
from typing import Any

import config
import db
import emoji
import lzt
from countries import COUNTRIES, flag, name_ru

log = logging.getLogger("numbers.shop")

MSK = dt.timezone(dt.timedelta(hours=3))
bot = None                       # ставит main.py: нужен для уведомлений

#: Снимок витрины: страна → (время, лоты). Обновляет воркер по кругу,
#: чтобы главный экран открывался мгновенно и не жёг лимит LZT.
SNAP: dict[str, tuple[float, list[dict]]] = {}
#: Лента «завоза»: новые лоты, которых не было в прошлом снимке.
ARRIVALS: list[dict] = []
_seen: dict[str, set[int]] = {}
#: Последний успех и последняя ошибка LZT — для витрины, /lzt и админки.
LZT_STATE: dict = {"ok_at": 0.0, "error": "", "error_at": 0.0, "crawled": 0,
                   "buy_fails": 0, "buy_paused": False, "buy_error": ""}
#: После стольких отказов LZT подряд (разные лоты) покупки ставятся на паузу:
#: иначе каждый покупатель получает только «не удалось, деньги вернулись».
BUY_FAILS_PAUSE = 3
_code_at: dict[int, float] = {}
#: Покупки одного человека идут строго по очереди: иначе 50 параллельных
#: запросов проскочат проверки (лимит, бан) одновременно.
_locks: dict[int, asyncio.Lock] = {}
_promo_tries: dict[int, list[float]] = {}
_ref_checked: dict[int, float] = {}


def _lock(uid: int) -> asyncio.Lock:
    if uid not in _locks:
        if len(_locks) > 50_000:
            _locks.clear()
        _locks[uid] = asyncio.Lock()
    return _locks[uid]


def allowed_lot(lot: dict | None) -> bool:
    """Продаём только то, что сами показали: Telegram, наши страны, без
    спамблока и только разрешённого происхождения (никаких stealer/phishing)."""
    if not lot or lot["country"] not in COUNTRIES:
        return False
    if lot["cost"] <= 0 or lot["cost"] > config.LZT_MAX_PRICE:
        return False
    if config.LZT_NO_SPAM and lot.get("spam"):
        return False
    origin = lot.get("origin") or ""
    return not origin or origin in config.LZT_ORIGINS


# ── Цены ──────────────────────────────────────────────────────────────

def price_kop(cost_rub: float, promo: int = 0) -> int:
    """Наша цена в копейках, округлённая вверх до рубля."""
    base = max(cost_rub * (1 + config.MARKUP), cost_rub + config.MIN_MARGIN_RUB)
    if promo > 0:
        base = max(base * (1 - promo / 100), cost_rub + 1)
    return int(math.ceil(base)) * 100


def stars_for(kop: int) -> int:
    """Сколько звёзд за пополнение на kop копеек (в звёздах ×STARS_MARKUP)."""
    return max(1, math.ceil(kop / 100 / config.STAR_RUB * config.STARS_MARKUP))


def money(kop: int) -> str:
    rub = kop / 100
    return f"{rub:,.0f} ₽".replace(",", " ") if rub == int(rub) else f"{rub:,.2f} ₽".replace(",", " ")


async def _promos() -> dict[str, int]:
    return await db.promos()


def _public(lot: dict, promos: dict[str, int]) -> dict:
    p = promos.get(lot["country"], 0)
    out = {k: v for k, v in lot.items() if k != "cost"}
    out["price"] = price_kop(lot["cost"], p)
    if p:
        out["old"] = price_kop(lot["cost"], 0)
    out["promo"] = p
    return out


# ── Витрина ───────────────────────────────────────────────────────────

async def refresh_country(c3: str) -> list[dict]:
    lots = await lzt.search(country=c3, pages=2)
    ids = {x["id"] for x in lots}
    before = _seen.get(c3)
    if before is not None:
        new = [x for x in lots if x["id"] not in before]
        if len(new) >= 3:
            ARRIVALS.insert(0, {"country": c3, "count": len(new), "at": int(time.time()),
                                "from": min(x["cost"] for x in new)})
            del ARRIVALS[40:]
    _seen[c3] = ids
    SNAP[c3] = (time.time(), lots)
    return lots


def _ingest(lots: list[dict]) -> None:
    """Раскладывает лоты общего обхода по странам и отмечает «завоз»."""
    by: dict[str, dict[int, dict]] = {}
    for x in lots:
        if x["country"] in COUNTRIES:
            by.setdefault(x["country"], {})[x["id"]] = x
    now = time.time()
    for c3, items in by.items():
        lst = sorted(items.values(), key=lambda x: x["cost"])
        before = _seen.get(c3)
        if before is not None:
            new = [x for x in lst if x["id"] not in before]
            if len(new) >= 3:
                ARRIVALS.insert(0, {"country": c3, "count": len(new), "at": int(now),
                                    "from": min(x["cost"] for x in new)})
                del ARRIVALS[40:]
        _seen[c3] = {x["id"] for x in lst}
        SNAP[c3] = (now, lst)
    for c3 in list(SNAP):
        if c3 not in by and now - SNAP[c3][0] > 3 * config.CRAWL_EVERY:
            SNAP.pop(c3)          # страна пропала из выдачи надолго — убираем


async def snapshot_worker() -> None:
    """Витрина из общего обхода каталога LZT: ~40 запросов раз в CRAWL_EVERY секунд.

    Фильтр страны у маркета ненадёжен, поэтому берём дешёвые и новые лоты
    всего каталога страницами и раскладываем по странам у себя.
    """
    if config.LZT_DEMO:
        while True:
            for c3 in COUNTRIES:
                try:
                    await refresh_country(c3)
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(0.05)
            await asyncio.sleep(60)
    while True:
        try:
            if not lzt.COUNTRY_FMT["probed"]:
                await lzt.probe_country_format()
            cheap = await lzt.crawl("price_to_up", config.CRAWL_CHEAP_PAGES)
            fresh = await lzt.crawl("pdate_to_down", config.CRAWL_NEW_PAGES)
            _ingest(cheap + fresh)
            LZT_STATE.update(ok_at=time.time(), error="", crawled=len(cheap) + len(fresh))
            log.info("витрина: %s лотов, %s стран", len(cheap) + len(fresh), len(SNAP))
        except Exception as exc:  # noqa: BLE001 — воркер не умирает
            # Не молчим: без этого пустой каталог выглядит как «нет товара».
            LZT_STATE.update(error=f"{type(exc).__name__}: {exc}"[:300], error_at=time.time())
            log.warning("LZT: %s", exc)
            await _admin_note(f"{emoji.tag('🛡')} LZT не отдаёт лоты: {html.escape(str(exc))[:300]}\n"
                              "Проверьте LZT_TOKEN (право market) и баланс. Подробно: /lzt", key="lzt_down")
        await asyncio.sleep(config.CRAWL_EVERY)


async def home() -> dict:
    """Главный экран: страны с ценой «от», новинки дня, акции, завоз, мгновенные."""
    promos = await _promos()
    ready = await db.reserve_ready()
    instant: dict[str, list] = {}
    for r in ready:
        instant.setdefault(r["country"], []).append(r)
    countries, fresh = [], []
    day_ago = time.time() - 86400
    for c3, (_, lots) in SNAP.items():
        if not lots and c3 not in instant:
            continue
        cheapest = min((x["cost"] for x in lots), default=None)
        inst = instant.get(c3) or []
        countries.append({
            "country": c3, "count": len(lots), "instant": len(inst),
            "from": price_kop(cheapest, promos.get(c3, 0)) if cheapest is not None else
                    price_kop(min(r["cost_kop"] for r in inst) / 100, promos.get(c3, 0)),
            "promo": promos.get(c3, 0),
        })
        fresh += [x for x in lots if x["published"] >= day_ago]
    total_lots = sum(len(v[1]) for v in SNAP.values())
    countries.sort(key=lambda x: (-(x["instant"] > 0), -x["count"]))
    fresh.sort(key=lambda x: -x["published"])
    inst_cards = []
    for c3, rows in instant.items():
        cheapest = min(r["cost_kop"] for r in rows) / 100
        inst_cards.append({"country": c3, "count": len(rows), "price": price_kop(cheapest, promos.get(c3, 0))})
    return {
        "countries": countries,
        "fresh": [_public(x, promos) for x in fresh[:12]],
        "promos": [{"country": c, "percent": p} for c, p in promos.items()],
        "arrivals": ARRIVALS[:10],
        "instant": inst_cards,
        "demo": config.LZT_DEMO,
        "total": total_lots,
        "buy_paused": LZT_STATE["buy_paused"] and not config.LZT_DEMO,
        # Каталог пуст из-за сбоя маркета, а не потому, что товара нет.
        "market_down": not countries and bool(LZT_STATE["error"]),
    }


async def lots(country: str, f: dict) -> list[dict]:
    """Лоты страны с фильтрами витрины."""
    if country not in COUNTRIES:
        return []
    items = await lzt.search(country=country, pages=3)
    if items:
        # Фильтр страны работает — дополняем витрину свежими лотами этой страны.
        merged = {x["id"]: x for x in SNAP.get(country, (0, []))[1]} | {x["id"]: x for x in items}
        SNAP[country] = (time.time(), sorted(merged.values(), key=lambda x: x["cost"]))
    items = SNAP.get(country, (0, []))[1]
    promos = await _promos()
    out = []
    pmin, pmax = float(f.get("pmin") or 0) * 100, float(f.get("pmax") or 0) * 100
    for x in items:
        if await db.lzt_item_taken(x["id"]):
            continue
        pub = _public(x, promos)
        if pmin and pub["price"] < pmin or pmax and pub["price"] > pmax:
            continue
        if f.get("premium") and not x["premium"]:
            continue
        if f.get("nopass") and x["password"]:
            continue
        if f.get("origin") and x["origin"] != f["origin"]:
            continue
        if f.get("fresh") and x["published"] < time.time() - 86400:
            continue
        out.append(pub)
    sort = f.get("sort") or "cheap"
    if sort == "new":
        out.sort(key=lambda x: -x["published"])
    elif sort == "expensive":
        out.sort(key=lambda x: -x["price"])
    elif sort == "old":
        out.sort(key=lambda x: -x["session_days"])
    else:
        out.sort(key=lambda x: x["price"])
    return out[:600]


def _cached_lot(item_id: int) -> dict | None:
    for _, items in SNAP.values():
        for x in items:
            if x["id"] == item_id:
                return x
    for _, items in lzt._cache.values():  # noqa: SLF001 — тот же процесс
        for x in items:
            if x["id"] == item_id:
                return x
    return None


# ── Покупка ───────────────────────────────────────────────────────────

class ShopError(Exception):
    def __init__(self, code: str, **extra: Any):
        super().__init__(code)
        self.code = code
        self.extra = extra


async def guard(uid: int) -> None:
    """Перед любой покупкой: бан, принятые условия, суточный лимит.

    Лимит — главная защита от спам-ферм: им нужны десятки и сотни
    аккаунтов сразу, обычному человеку — один-два.
    """
    u = await db.get_user(uid)
    if u is None:
        raise ShopError("not_found")
    if u["banned"]:
        raise ShopError("banned")
    if LZT_STATE["buy_paused"] and not config.LZT_DEMO:
        raise ShopError("buy_paused")
    if not u["terms_at"]:
        raise ShopError("terms")
    if u["trusted"]:
        return
    limit = config.MAX_PER_DAY_NEW if time.time() - int(u["created_at"]) < 86400 else config.MAX_PER_DAY
    if limit > 0 and await db.bought_today(uid) >= limit:
        raise ShopError("day_limit", limit=limit)


async def buy_instant(uid: int, country: str) -> dict:
    """Мгновенная выдача из резерва."""
    async with _lock(uid):
        return await _buy_instant(uid, country)


async def _buy_instant(uid: int, country: str) -> dict:
    await guard(uid)
    promos = await _promos()
    for r in await db.reserve_ready(country):
        if not await db.reserve_claim(int(r["id"])):
            continue          # забрал соседний запрос — берём следующий
        # Аккаунт мог «умереть», пока лежал в резерве. Давно не проверяли —
        # проверяем через гарантию LZT; невалидный не продаём, а списываем.
        if time.time() - max(int(r["checked_at"] or 0), int(r["bought_at"])) > config.RESERVE_CHECK_MIN * 60:
            state = await lzt.check_owned(int(r["item_id"]))
            if state == "invalid":
                await db.run("UPDATE reserve SET status='dead' WHERE id=?", (r["id"],))
                log.warning("резерв #%s невалиден — списан, LZT вернёт деньги", r["id"])
                continue
            await db.run("UPDATE reserve SET checked_at=? WHERE id=?", (db.now(), r["id"]))
        price = price_kop(r["cost_kop"] / 100, promos.get(country, 0))
        if not await db.take_kop(uid, price, "buy", f"reserve#{r['id']}"):
            await db.reserve_release(int(r["id"]))
            raise ShopError("no_money", need=price)
        oid = await db.create_order(uid, "reserve", int(r["item_id"]), country, int(r["cost_kop"]), price)
        await db.finish_order(oid, r["phone"], r["password"], json.loads(r["info"] or "{}"))
        await _admin_note(f"{emoji.tag('⚡')} Мгновенная продажа #{oid}: {emoji.tag(flag(country))}{name_ru(country)} · "
                          f"{money(price)} (закупка {money(int(r['cost_kop']))})\n{await who(uid)}")
        return await order_view(await db.get_order(oid))
    raise ShopError("sold_out")


async def buy_lot(uid: int, item_id: int, expected: int) -> dict:
    """Покупка лота с LZT под заказ. Деньги списываются сразу, LZT — в фоне."""
    async with _lock(uid):
        return await _buy_lot(uid, item_id, expected)


async def _buy_lot(uid: int, item_id: int, expected: int) -> dict:
    await guard(uid)
    # Только лоты из нашей же выдачи. Произвольный item_id с маркета (другая
    # категория, украденный аккаунт, спамблок) купить через нас нельзя.
    lot = _cached_lot(item_id)
    if not allowed_lot(lot):
        raise ShopError("gone")
    if await db.lzt_item_taken(item_id):
        raise ShopError("gone")
    promos = await _promos()
    price = price_kop(lot["cost"], promos.get(lot["country"], 0))
    if expected and price != expected:
        raise ShopError("price_changed", price=price)
    if not await db.take_kop(uid, price, "buy", f"lzt#{item_id}"):
        raise ShopError("no_money", need=price)
    oid = await db.create_order(uid, "live", item_id, lot["country"], int(round(lot["cost"] * 100)), price)
    asyncio.create_task(_fulfil(oid, item_id, lot["cost"]))
    return await order_view(await db.get_order(oid))


async def _fulfil(oid: int, item_id: int, cost: float) -> None:
    order = await db.get_order(oid)
    uid = int(order["user_id"])
    try:
        got = await lzt.buy(item_id, cost)
    except Exception as exc:  # noqa: BLE001 — любая ошибка = возврат
        log.warning("заказ #%s: LZT не продал %s: %s", oid, item_id, exc)
        low = str(exc).lower()
        # «лот уже купили / цена изменилась» — обычное дело; 403 и права — сбой аккаунта LZT.
        if "403" in low or "прав" in low or "permission" in low or "401" in low:
            LZT_STATE["buy_fails"] += 1
            LZT_STATE["buy_error"] = str(exc)[:300]
            if LZT_STATE["buy_fails"] >= BUY_FAILS_PAUSE and not LZT_STATE["buy_paused"]:
                LZT_STATE["buy_paused"] = True
                await _admin_note(
                    f"{emoji.tag('🛡')} <b>Покупки на паузе</b>: LZT {BUY_FAILS_PAUSE} раза подряд отказал в покупке "
                    f"(«{html.escape(str(exc))[:200]}»). Деньги покупателям вернулись.\n"
                    "Проверьте аккаунт LZT: купите любой лот вручную на сайте — он покажет причину. "
                    "Включить покупки снова: /buy_on")
        row = await db.fail_order(oid, str(exc))
        if row is not None:
            await db.add_kop(uid, int(row["price_kop"]), "refund", f"order#{oid}")
            await notify(uid, "refund", order=oid, amount=money(int(row["price_kop"])))
            await _admin_note(f"{emoji.tag('↩️')} Заказ #{oid} не куплен на LZT, деньги вернули: {exc}")
        return
    LZT_STATE.update(buy_fails=0)
    await db.finish_order(oid, got["phone"], got["password"], got["raw"], int(round(got["cost"] * 100)))
    await notify(uid, "done", order=oid, phone=got["phone"])
    await _admin_note(f"{emoji.tag('🛒')} Продажа #{oid}: {emoji.tag(flag(order['country']))}{name_ru(order['country'])} · "
                      f"{money(int(order['price_kop']))} (закупка {money(int(round(got['cost'] * 100)))})\n"
                      f"{await who(uid)}")


async def order_view(o) -> dict:
    info = json.loads(o["info"] or "{}")
    # После возврата денег данные аккаунта больше не показываем.
    hide = o["status"] == "refunded"
    return {
        "id": o["id"], "status": o["status"], "source": o["source"], "country": o["country"],
        "price": o["price_kop"], "phone": "" if hide else o["phone"], "password": "" if hide else o["password"],
        "created": o["created_at"], "done": o["done_at"], "error": "" if o["status"] != "refunded" else "refunded",
        "demo": bool(info.get("demo")),
        "can_report": o["status"] == "done" and bool(o["done_at"])
                      and time.time() - int(o["done_at"]) < config.GUARANTEE_H * 3600,
        "guarantee_h": config.GUARANTEE_H,
    }


async def report(uid: int, oid: int) -> dict:
    """«Аккаунт не работает»: проверка через гарантию LZT.

    Невалиден — LZT возвращает деньги нам, мы — покупателю на баланс.
    Валиден — просим войти ещё раз. Не чаще раза в 30 минут на заказ.
    """
    o = await db.get_order(oid)
    if o is None or int(o["user_id"]) != uid or o["status"] != "done":
        raise ShopError("not_found")
    if time.time() - int(o["done_at"] or 0) > config.GUARANTEE_H * 3600:
        raise ShopError("guarantee_over")
    cur = await db.run("UPDATE orders SET reported=? WHERE id=? AND reported<?",
                       (db.now(), oid, db.now() - 1800))
    if cur.rowcount != 1:
        raise ShopError("slow_down")
    state = await lzt.check_owned(int(o["item_id"]))
    if state != "invalid":
        await _admin_note(f"{emoji.tag('🛡')} Жалоба на заказ #{oid}: проверка LZT = {state}\n{await who(uid)}")
        return {"result": state}
    cur = await db.run("UPDATE orders SET status='refunded', error='invalid' WHERE id=? AND status='done'", (oid,))
    if cur.rowcount == 1 and int(o["price_kop"]) > 0:
        await db.add_kop(uid, int(o["price_kop"]), "refund", f"invalid#{oid}")
    await _admin_note(f"{emoji.tag('🛡')} Заказ #{oid} невалиден — LZT вернёт закупку, покупателю вернули "
                      f"{money(int(o['price_kop']))}\n{await who(uid)}")
    return {"result": "refunded"}


async def get_code(uid: int, oid: int) -> dict:
    o = await db.get_order(oid)
    if o is None or int(o["user_id"]) != uid or o["status"] != "done":
        raise ShopError("not_found")
    last = _code_at.get(oid, 0)
    if time.time() - last < 5:
        raise ShopError("slow_down")
    _code_at[oid] = time.time()
    try:
        got = await lzt.login_code(int(o["item_id"]))
    except lzt.LztError as exc:
        log.info("код для #%s: %s", oid, exc)
        got = None
    if not got:
        raise ShopError("no_code")
    return got


# ── Резерв ────────────────────────────────────────────────────────────

async def keep_reserve() -> None:
    """Докупает резерв до RESERVE_SIZE самыми дешёвыми лотами."""
    if config.RESERVE_SIZE <= 0 or not config.RESERVE_COUNTRIES:
        return
    stale = await db.all_("SELECT * FROM reserve WHERE status='ready' AND MAX(checked_at, bought_at)<? "
                          "ORDER BY checked_at LIMIT 5", (db.now() - config.RESERVE_CHECK_MIN * 60,))
    for r in stale:
        state = await lzt.check_owned(int(r["item_id"]))
        if state == "invalid":
            await db.run("UPDATE reserve SET status='dead' WHERE id=? AND status='ready'", (r["id"],))
            log.warning("резерв #%s невалиден — списан", r["id"])
        elif state == "valid":
            await db.run("UPDATE reserve SET checked_at=? WHERE id=?", (db.now(), r["id"]))
    per = max(1, config.RESERVE_SIZE // len(config.RESERVE_COUNTRIES))
    for c3 in config.RESERVE_COUNTRIES:
        have = len(await db.reserve_ready(c3))
        if have >= per:
            continue
        bal = await lzt.balance()
        lots = sorted((await lzt.search(country=c3, pmax=config.RESERVE_MAX_PRICE)), key=lambda x: x["cost"])
        for lot in lots:
            if have >= per:
                break
            if lot["cost"] > config.RESERVE_MAX_PRICE or lot["password"]:
                continue
            if bal is not None and bal < lot["cost"]:
                await _admin_note(f"{emoji.tag('💳')} На LZT не хватает денег на резерв — пополните баланс маркета.", key="lzt_low")
                return
            if await db.lzt_item_taken(lot["id"]):
                continue
            try:
                got = await lzt.buy(lot["id"], lot["cost"])
            except Exception as exc:  # noqa: BLE001
                log.info("резерв %s: %s", lot["id"], exc)
                continue
            await db.reserve_add(lot["id"], c3, int(round(got["cost"] * 100)), got["phone"], got["password"], got["raw"])
            have += 1
            if bal is not None:
                bal -= got["cost"]
            log.info("резерв +1 %s за %.2f ₽", c3, got["cost"])


# ── Конкурс ───────────────────────────────────────────────────────────

def today() -> str:
    return dt.datetime.now(MSK).strftime("%Y-%m-%d")


async def giveaway_state(uid: int | None = None) -> dict:
    day = today()
    n = await db.one("SELECT COUNT(*) n FROM giveaway_entries WHERE day=?", (day,))
    joined = bool(uid and await db.one("SELECT 1 FROM giveaway_entries WHERE day=? AND user_id=?", (day, uid)))
    last = await db.all_("SELECT g.day, g.status, g.winner_id, u.name FROM giveaways g "
                         "LEFT JOIN users u ON u.id=g.winner_id WHERE g.day<? ORDER BY g.day DESC LIMIT 5", (day,))
    at = dt.datetime.now(MSK).replace(hour=config.GIVEAWAY_HOUR, minute=0, second=0, microsecond=0)
    if dt.datetime.now(MSK) >= at:
        at += dt.timedelta(days=1)
    return {
        "on": config.GIVEAWAY_ON, "day": day, "count": n["n"], "joined": joined,
        "draw_at": int(at.timestamp()), "channel": config.CHANNEL_URL, "prize_max": config.GIVEAWAY_MAX_PRICE,
        "winners": [{"day": r["day"], "status": r["status"], "name": _mask(r["name"] or "")} for r in last],
    }


def _mask(name: str) -> str:
    return name[:1] + "•" * max(2, min(5, len(name) - 1)) if name else "—"


_subs: dict[int, tuple[float, bool]] = {}


def forget_sub(uid: int) -> None:
    _subs.pop(uid, None)


async def is_subscribed(uid: int) -> bool:
    """Подписан ли на CHANNEL. Ответ кэшируется: подписан — на 5 минут, нет — на 15 секунд."""
    if not config.CHANNEL:
        return True
    if bot is None:
        return False
    hit = _subs.get(uid)
    if hit and time.time() - hit[0] < (300 if hit[1] else 15):
        return hit[1]
    try:
        m = await bot.get_chat_member(config.CHANNEL, uid)
    except Exception as exc:  # noqa: BLE001 — бот не админ канала, канал переименован
        # Проверить нельзя — не блокируем людей, а сообщаем админу (раз в час).
        log.warning("проверка подписки %s: %s", uid, exc)
        await _admin_note(f"{emoji.tag('🛡')} Не могу проверить подписку на {html.escape(config.CHANNEL)}: "
                          f"{html.escape(str(exc))[:200]}\nСделайте бота админом канала. Пока пропускаю всех.",
                          key="sub_check")
        return True
    ok = m.status in ("member", "administrator", "creator") or (m.status == "restricted" and getattr(m, "is_member", False))
    _subs[uid] = (time.time(), ok)
    if len(_subs) > 200_000:
        _subs.clear()
    return ok


async def giveaway_join(uid: int) -> dict:
    if not config.GIVEAWAY_ON:
        raise ShopError("off")
    u = await db.get_user(uid)
    if u and u["banned"]:
        raise ShopError("banned")
    if not await is_subscribed(uid):
        raise ShopError("not_subscribed", channel=config.CHANNEL_URL)
    await db.run("INSERT OR IGNORE INTO giveaway_entries(day,user_id) VALUES(?,?)", (today(), uid))
    return await giveaway_state(uid)


async def _prize(max_rub: float | None = None) -> tuple[str, int, int, str, str, dict, str] | None:
    """(источник, item_id, закупка коп, телефон, 2FA, info, страна) или None."""
    max_rub = max_rub or config.GIVEAWAY_MAX_PRICE
    for r in sorted(await db.reserve_ready(), key=lambda x: x["cost_kop"]):
        if r["cost_kop"] <= max_rub * 100 and await db.reserve_claim(int(r["id"]), "prize"):
            return ("reserve", int(r["item_id"]), int(r["cost_kop"]), r["phone"], r["password"],
                    json.loads(r["info"] or "{}"), r["country"])
    cheap = sorted(await lzt.search(pmax=max_rub), key=lambda x: x["cost"])
    for lot in cheap[:5]:
        if lot["password"] or await db.lzt_item_taken(lot["id"]):
            continue
        try:
            got = await lzt.buy(lot["id"], lot["cost"])
        except Exception as exc:  # noqa: BLE001
            log.info("приз %s: %s", lot["id"], exc)
            continue
        return ("live", lot["id"], int(round(got["cost"] * 100)), got["phone"], got["password"],
                got["raw"], lot["country"])
    return None


async def draw(force: bool = False) -> dict:
    """Розыгрыш дня. Вызывает воркер в GIVEAWAY_HOUR по МСК (или админ)."""
    day = today()
    row = await db.one("SELECT status FROM giveaways WHERE day=?", (day,))
    if row and row["status"] != "open" and not force:
        return {"status": row["status"]}
    await db.run("INSERT OR IGNORE INTO giveaways(day,created_at) VALUES(?,?)", (day, db.now()))
    entries = [r["user_id"] for r in await db.all_("SELECT user_id FROM giveaway_entries WHERE day=?", (day,))]
    if not entries:
        await db.run("UPDATE giveaways SET status='skipped', note='нет участников' WHERE day=?", (day,))
        return {"status": "skipped", "note": "нет участников"}
    st = await db.stats(int(time.time()) - 86400)
    if st["margin"] < config.GIVEAWAY_MAX_PRICE * 100 and not force:
        await db.run("UPDATE giveaways SET status='skipped', note='маржа за сутки меньше приза' WHERE day=?", (day,))
        await _admin_note(f"{emoji.tag('🎁')} Конкурс {day} пропущен: маржа за сутки {money(st['margin'])} меньше приза.")
        return {"status": "skipped", "note": "маржа меньше приза"}
    random.shuffle(entries)
    winner = None
    for uid in entries[:50]:
        if await is_subscribed(uid):
            winner = uid
            break
    if winner is None:
        await db.run("UPDATE giveaways SET status='skipped', note='никто не подписан' WHERE day=?", (day,))
        return {"status": "skipped", "note": "никто не подписан"}
    prize = await _prize()
    if prize is None:
        await _admin_note(f"{emoji.tag('🎁')} Конкурс {day}: не нашёл приз до {config.GIVEAWAY_MAX_PRICE:.0f} ₽ — розыгрыш отложен.")
        return {"status": "open", "note": "нет приза"}
    src, item_id, cost, phone, pwd, info, c3 = prize
    oid = await db.create_order(winner, "giveaway", item_id, c3, cost, 0)
    await db.finish_order(oid, phone, pwd, info)
    await db.run("UPDATE giveaways SET status='done', winner_id=?, order_id=? WHERE day=?", (winner, oid, day))
    await notify(winner, "won", order=oid)
    await _admin_note(f"{emoji.tag('🎁')} Конкурс {day}: победитель {await who(winner)}, приз {emoji.tag(flag(c3))}{name_ru(c3)} за {money(cost)}")
    return {"status": "done", "winner": winner, "order": oid, "entries": len(entries)}


# ── Рефералы ──────────────────────────────────────────────────────────

def ref_link(uid: int) -> str:
    return f"https://t.me/{config.BOT_USERNAME}?start=ref{uid}" if config.BOT_USERNAME else f"ref{uid}"


async def ref_state(uid: int) -> dict:
    u = await db.get_user(uid)
    row = await db.one("SELECT COUNT(*) n, COALESCE(SUM(ref_ok),0) ok FROM users WHERE ref_by=?", (uid,))
    used = int(u["ref_used"]) if u else 0
    have = max(0, int(row["ok"]) - used)
    return {
        "link": ref_link(uid), "invited": row["n"], "confirmed": row["ok"],
        "progress": min(have, config.REF_GOAL), "goal": config.REF_GOAL,
        "claimable": have // config.REF_GOAL, "prize_max": config.REF_PRIZE_MAX,
        "claimed": used // config.REF_GOAL, "need_channel": bool(config.CHANNEL), "channel": config.CHANNEL_URL,
    }


async def ref_confirm(uid: int, full: bool = False) -> int:
    """Засчитывает друзей, подписанных на канал. Не чаще раза в минуту на человека
    (каждая проверка — запрос к Telegram). full=True перед выдачей приза
    перепроверяет всех: отписавшиеся друзья перестают считаться."""
    if time.time() - _ref_checked.get(uid, 0) < 60 and not full:
        return 0
    _ref_checked[uid] = time.time()
    where = "" if full else "AND ref_ok=0"
    rows = await db.all_(f"SELECT id FROM users WHERE ref_by=? {where} LIMIT 200", (uid,))
    n = 0
    for r in rows:
        ok = await is_subscribed(int(r["id"]))
        await db.run("UPDATE users SET ref_ok=? WHERE id=?", (1 if ok else 0, r["id"]))
        n += ok
    return n


async def ref_subscribed(uid: int) -> bool:
    """Друг подписался на канал — засчитываем его пригласившему сразу и пишем тому об этом.

    Вызывается, как только подписка подтверждена (кнопка «Проверить подписку»,
    /start подписчика, проверка в Mini App). Засчитывается один раз:
    UPDATE с условием ref_ok=0.
    """
    u = await db.get_user(uid)
    if not u or not u["ref_by"] or u["ref_ok"]:
        return False
    if not await is_subscribed(uid):
        return False
    cur = await db.run("UPDATE users SET ref_ok=1 WHERE id=? AND ref_ok=0", (uid,))
    if cur.rowcount != 1:
        return False
    inviter = int(u["ref_by"])
    st = await ref_state(inviter)
    await notify(inviter, "ref_ok", name=u["name"] or "—", n=st["progress"], goal=st["goal"])
    return True


async def ref_claim(uid: int) -> dict:
    """Приз за каждые REF_GOAL друзей — самый дешёвый аккаунт до REF_PRIZE_MAX ₽."""
    async with _lock(uid):
        return await _ref_claim(uid)


async def _ref_claim(uid: int) -> dict:
    u = await db.get_user(uid)
    if u and u["banned"]:
        raise ShopError("banned")
    if time.time() - _ref_checked.get(uid, 0) < 10:
        raise ShopError("slow_down")
    await ref_confirm(uid, full=True)
    st = await ref_state(uid)
    if st["claimable"] < 1:
        raise ShopError("ref_not_enough", need=config.REF_GOAL - st["progress"])
    today_n = await db.one("SELECT COUNT(*) n FROM orders WHERE source='ref' AND created_at>=?",
                           (int(time.time()) - 86400,))
    if today_n["n"] >= config.REF_DAILY_MAX:
        raise ShopError("ref_limit")
    if not await db.use_ref_prize(uid, config.REF_GOAL, int(st["confirmed"])):
        raise ShopError("ref_not_enough", need=config.REF_GOAL)
    prize = await _prize(config.REF_PRIZE_MAX)
    if prize is None:
        await db.run("UPDATE users SET ref_used=ref_used-? WHERE id=?", (config.REF_GOAL, uid))
        raise ShopError("no_prize")
    src, item_id, cost, phone, pwd, info, c3 = prize
    oid = await db.create_order(uid, "ref", item_id, c3, cost, 0)
    await db.finish_order(oid, phone, pwd, info)
    await _admin_note(f"{emoji.tag('👥')} Реферальный приз #{oid}: {emoji.tag(flag(c3))}{name_ru(c3)} за {money(cost)}\n{await who(uid)}")
    return await order_view(await db.get_order(oid))


# ── Уведомления ───────────────────────────────────────────────────────

async def who(uid: int) -> str:
    u = await db.get_user(uid)
    if not u:
        return f"id {uid}"
    # Имя задаёт сам человек — экранируем, иначе <a href> в имени попадёт админу.
    tag = f"@{html.escape(u['username'])}" if u["username"] else html.escape(u["name"] or "")
    return f"{tag} · <code>{uid}</code>"


async def transfer(src: int, to: str, kop: int) -> dict:
    """Перевод другу — общий для Mini App и текстовой версии."""
    if kop < 1000 or kop > 10_000_000:
        raise ShopError("min:10" if kop < 1000 else "bad")
    u = await db.get_user(src)
    if u is None or u["banned"]:
        raise ShopError("banned")
    dst = await db.find_user(to[:64])
    if dst is None:
        raise ShopError("user_not_found")
    if int(dst["id"]) == src:
        raise ShopError("self_send")
    async with _lock(src):
        if not await db.transfer(src, int(dst["id"]), kop):
            raise ShopError("no_money", need=kop)
    await notify(int(dst["id"]), "received", amount=money(kop), name=u["name"] or str(src))
    return {"to": dst["name"] or dst["username"] or dst["id"], "dst": int(dst["id"])}


async def promo(uid: int, code: str) -> int:
    """Промокод: не больше 10 попыток в час — перебором коды не подобрать."""
    u = await db.get_user(uid)
    if u is None or u["banned"]:
        raise ShopError("banned")
    tries = [t for t in _promo_tries.get(uid, []) if time.time() - t < 3600]
    if len(tries) >= 10:
        raise ShopError("slow_down")
    tries.append(time.time())
    _promo_tries[uid] = tries
    got = await db.use_promo(uid, code[:32])
    if isinstance(got, str):
        raise ShopError(got)
    return got


async def notify(uid: int, kind: str, **kw: Any) -> None:
    if bot is None:
        return
    import bot as botmod  # тексты и кнопки живут в боте
    try:
        await botmod.notify(uid, kind, **kw)
    except Exception as exc:  # noqa: BLE001 — человек мог заблокировать бота
        log.debug("уведомление %s %s: %s", uid, kind, exc)


_admin_keys: dict[str, float] = {}


async def _admin_note(text: str, key: str = "") -> None:
    if bot is None:
        return
    if key:
        if time.time() - _admin_keys.get(key, 0) < 3600:
            return
        _admin_keys[key] = time.time()
    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid, text)
        except Exception:  # noqa: BLE001
            pass
