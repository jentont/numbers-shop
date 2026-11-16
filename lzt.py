"""Клиент LZT Market для Telegram-аккаунтов.

Эндпоинты (api.lzt.market, заголовок Authorization: Bearer <token>,
токену нужен scope market):

* GET  /telegram                    — поиск лотов (лимит 120 запросов в минуту)
* GET  /{item_id}                   — лот
* POST /{item_id}/fast-buy          — покупка; price — потолок цены
* GET  /{item_id}/telegram-login-code — коды входа, пришедшие на аккаунт
* GET  /me                          — наш профиль и баланс

Ответы LZT меняются, поэтому поля разбираются защитно (несколько
возможных имён), а сырой ответ покупки сохраняется в заказ целиком.

Демо-режим (нет токена или LZT_DEMO=1) отдаёт выдуманные лоты и
«покупает» их без денег — витрину и все сценарии можно прогнать до
того, как на маркете появится баланс.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from typing import Any

import aiohttp

import config
from countries import COUNTRIES, to_iso3

log = logging.getLogger("numbers.lzt")

TIMEOUT = aiohttp.ClientTimeout(total=60)   # fast-buy проверяет аккаунт, это небыстро
_session: aiohttp.ClientSession | None = None
_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = asyncio.Lock()
_last_call = 0.0


class LztError(RuntimeError):
    """Маркет отказал. Текст — для лога и админа, покупателю — общий."""


async def _sess() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=TIMEOUT)
    return _session


async def close() -> None:
    if _session is not None and not _session.closed:
        await _session.close()


async def _call(method: str, path: str, params: Any = None, json: dict | None = None) -> dict:
    global _last_call
    # Не чаще 2 запросов в секунду — с запасом под лимит 120/мин.
    async with _lock:
        wait = 0.5 - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()
    sess = await _sess()
    headers = {"Authorization": f"Bearer {config.LZT_TOKEN}", "Accept": "application/json"}
    for attempt in range(3):
        async with sess.request(method, f"{config.LZT_BASE}{path}", params=params,
                                json=json, headers=headers) as resp:
            text = await resp.text()
            try:
                data = await resp.json(content_type=None)
            except Exception:  # noqa: BLE001
                data = {"_raw": text[:300]}
            if resp.status == 429 and attempt < 2:
                await asyncio.sleep(3 * (attempt + 1))
                continue
            if resp.status >= 400 or (isinstance(data, dict) and data.get("errors")):
                err = data.get("errors") if isinstance(data, dict) else None
                msg = "; ".join(map(str, err)) if isinstance(err, list) else str(err or text[:200])
                raise LztError(f"{method} {path} → {resp.status}: {msg}")
            return data if isinstance(data, dict) else {"data": data}
    raise LztError(f"{method} {path}: слишком много запросов")


# ── Нормализация лота ─────────────────────────────────────────────────

def _num(v: Any, default: float = 0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _yes(v: Any) -> bool:
    return v not in (None, 0, "0", "", False, "no", "false")


def normalize(it: dict) -> dict:
    """Лот LZT → то, что видит витрина. Ничего секретного здесь нет."""
    country = to_iso3(str(it.get("telegram_country") or it.get("country") or ""))
    price = _num(it.get("rub_price"), 0) or _num(it.get("price"), 0)
    last_seen = int(_num(it.get("telegram_last_seen"), 0))
    created = int(_num(it.get("telegram_session_created_at"), 0))
    return {
        "id": int(it.get("item_id") or 0),
        "country": country,
        "cost": round(price, 2),
        "title": str(it.get("title") or "")[:80],
        "origin": str(it.get("item_origin") or ""),
        "published": int(_num(it.get("published_date"), 0)),
        "premium": _yes(it.get("telegram_premium")),
        "spam": _yes(it.get("telegram_spam_block")),
        "password": _yes(it.get("telegram_password")),
        "stars": int(_num(it.get("telegram_stars_count"), 0)),
        "gifts": int(_num(it.get("telegram_gifts_count"), 0)),
        "channels": int(_num(it.get("telegram_channels_count"), 0)),
        "contacts": int(_num(it.get("telegram_contacts_count"), 0)),
        "dc": int(_num(it.get("telegram_dc_id"), 0)),
        "last_seen": last_seen,
        "session_days": int((time.time() - created) / 86400) if created else 0,
    }


def _login(item: dict) -> tuple[str, str]:
    """Телефон и пароль 2FA из ответа покупки — пробуем известные поля."""
    ld = item.get("loginData") or item.get("login_data") or {}
    phone = (item.get("telegram_phone") or ld.get("login") or item.get("phone")
             or (item.get("account_data") or {}).get("phone") or "")
    password = (ld.get("password") or item.get("telegram_2fa") or item.get("telegram_password_value") or "")
    phone = str(phone).strip()
    if phone and not phone.startswith("+"):
        digits = "".join(ch for ch in phone if ch.isdigit())
        phone = f"+{digits}" if digits else phone
    return phone, str(password or "")


# ── Публичные функции ─────────────────────────────────────────────────

async def search(country: str = "", pmin: float = 0, pmax: float = 0, premium: str = "",
                 order: str = "price_to_up", pages: int = 1) -> list[dict]:
    """Лоты одной страны (или всех) — с кэшем на CACHE_TTL секунд."""
    key = f"{country}|{pmin}|{pmax}|{premium}|{order}|{pages}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < config.CACHE_TTL:
        return hit[1]
    if config.LZT_DEMO:
        lots = _demo_lots(country)
    else:
        params: list[tuple[str, Any]] = [("order_by", order), ("currency", "rub")]
        if country:
            params.append(("country[]", country))
        if pmin:
            params.append(("pmin", pmin))
        params.append(("pmax", pmax or config.LZT_MAX_PRICE))
        if config.LZT_NO_SPAM:
            params.append(("spam", "no"))
        if premium in ("yes", "no"):
            params.append(("premium", premium))
        for o in config.LZT_ORIGINS:
            params.append(("origin[]", o))
        lots, after = [], None
        for _ in range(max(1, pages)):
            page = params + ([("after", after)] if after else [])
            data = await _call("GET", "/telegram", params=page)
            lots += [normalize(i) for i in data.get("items") or []]
            after = data.get("nextCursor")
            if not data.get("hasNextPage") or not after:
                break
    lots = [x for x in lots if x["id"] and x["cost"] > 0 and x["country"]]
    _cache[key] = (time.time(), lots)
    return lots


async def item(item_id: int) -> dict | None:
    if config.LZT_DEMO:
        for lot in _demo_lots(""):
            if lot["id"] == item_id:
                return lot
        return None
    data = await _call("GET", f"/{item_id}")
    raw = data.get("item") or data
    return normalize(raw) if raw.get("item_id") else None


async def buy(item_id: int, max_price: float) -> dict:
    """Покупает лот не дороже max_price ₽. Возвращает телефон, 2FA и сырой ответ."""
    if config.LZT_DEMO:
        await asyncio.sleep(1.2)
        lot = await item(item_id)
        if lot is None:
            raise LztError("демо: лот не найден")
        if random.random() < 0.05:
            raise LztError("демо: лот уже купили")
        dial = COUNTRIES.get(lot["country"], ("", "1", ""))[1]
        rnd = random.Random(item_id)
        phone = f"+{dial}{rnd.randint(10**8, 10**9 - 1)}"
        return {"phone": phone, "password": "", "cost": lot["cost"], "raw": {"demo": True}}
    data = await _call("POST", f"/{item_id}/fast-buy", json={"price": round(max_price, 2)})
    raw = data.get("item") or data
    phone, password = _login(raw)
    cost = _num(raw.get("rub_price"), 0) or _num(raw.get("price"), 0) or max_price
    # Сохраняем всё, что нужно для поддержки, кроме лишнего шума.
    keep = {k: raw.get(k) for k in ("item_id", "loginData", "telegram_phone", "telegram_country",
                                    "item_origin", "telegram_premium", "guarantee", "buyer") if k in raw}
    return {"phone": phone, "password": password, "cost": round(cost, 2), "raw": keep}


async def login_code(item_id: int) -> dict | None:
    """Самый свежий код входа: {"code": "12345", "date": unix} или None."""
    if config.LZT_DEMO:
        return {"code": f"{random.randint(10000, 99999)}", "date": int(time.time())}
    data = await _call("GET", f"/{item_id}/telegram-login-code")
    best = None
    for c in data.get("codes") or []:
        digits = "".join(ch for ch in str(c.get("code") or "") if ch.isdigit())
        if 4 <= len(digits) <= 6 and (best is None or _num(c.get("date")) > best["date"]):
            best = {"code": digits, "date": int(_num(c.get("date")))}
    if best is None:
        flat = "".join(ch for ch in str(data.get("code") or "") if ch.isdigit())
        if 4 <= len(flat) <= 6:
            best = {"code": flat, "date": 0}
    return best


async def check_owned(item_id: int) -> str:
    """Проверка купленного нами аккаунта через гарантию LZT.

    POST /{item_id}/check-guarantee: маркет проверяет аккаунт и, если он
    невалиден, возвращает нам деньги, лот закрывается. Ответ ручки строго
    не документирован, поэтому после проверки перечитываем лот: закрыт или
    возвращён — значит «invalid». Сырые ответы пишем в лог, чтобы на первом
    боевом запуске сверить поля.

    Возвращает "valid", "invalid" или "unknown" (маркет не ответил).
    """
    if config.LZT_DEMO:
        await asyncio.sleep(0.6)
        return "invalid" if random.random() < 0.08 else "valid"
    failed = False
    try:
        res = await _call("POST", f"/{item_id}/check-guarantee")
        log.info("check-guarantee %s: %s", item_id, str(res)[:300])
    except LztError as exc:
        log.info("check-guarantee %s: %s", item_id, exc)
        failed = True
    # Решаем только по состоянию лота: «невалиден» = маркет закрыл лот и вернул
    # нам деньги. По одному тексту ошибки покупателю не возвращаем — иначе
    # можно сломать аккаунт самому, нажать «не работает» и получить деньги,
    # которые маркет нам не вернёт.
    try:
        data = await _call("GET", f"/{item_id}")
    except LztError:
        return "unknown"
    raw = data.get("item") or data
    state = str(raw.get("item_state") or "").lower()
    g = raw.get("guarantee") or {}
    if state in ("closed", "deleted", "refunded") or (isinstance(g, dict) and g.get("cancelled")):
        return "invalid"
    return "unknown" if failed else "valid"


async def balance() -> float | None:
    """Баланс на LZT в рублях (None, если не узнать)."""
    if config.LZT_DEMO:
        return 5000.0
    try:
        data = await _call("GET", "/me")
    except LztError as exc:
        log.warning("баланс LZT: %s", exc)
        return None
    user = data.get("user") or data
    return _num(user.get("balance"), 0)


# ── Демо ──────────────────────────────────────────────────────────────

_DEMO_BASE = {  # примерные цены авторегов по странам, ₽
    "RUS": 28, "UKR": 35, "KAZ": 30, "BLR": 45, "UZB": 22, "KGZ": 24, "USA": 60, "GBR": 75,
    "DEU": 90, "FRA": 85, "NLD": 95, "POL": 55, "TUR": 18, "IND": 12, "IDN": 9, "PHL": 11,
    "VNM": 10, "THA": 25, "MYS": 40, "BRA": 16, "MEX": 20, "COL": 14, "CAN": 70, "NGA": 13,
    "EGY": 15, "KEN": 12, "PAK": 10, "BGD": 9, "MMR": 8, "GEO": 38, "ARM": 34, "AZE": 30,
    "ISR": 110, "ESP": 80, "ITA": 82, "ROU": 48, "CZE": 65, "PRT": 70, "ARE": 120, "SAU": 95,
}


def _demo_lots(country: str) -> list[dict]:
    """Стабильные в пределах 10 минут лоты: каждые 10 минут — «завоз»."""
    slot = int(time.time() // 600)
    out = []
    for c3, base in _DEMO_BASE.items():
        if country and c3 != country:
            continue
        n = 6 + int(hashlib.md5(f"{c3}{slot}".encode()).hexdigest(), 16) % 9
        for i in range(n):
            seed = int(hashlib.md5(f"{c3}-{i}-{slot // 6}".encode()).hexdigest()[:8], 16)
            rnd = random.Random(seed)
            fresh = i < 2
            out.append({
                "id": 9_000_000 + (seed % 900_000) * 10 + i,
                "country": c3,
                "cost": round(base * rnd.uniform(.75, 1.6) + (rnd.random() < .12) * base * 3, 2),
                "title": "",
                "origin": rnd.choice(["autoreg", "autoreg", "autoreg", "self_registration", "personal"]),
                "published": int(time.time()) - (rnd.randint(60, 3000) if fresh else rnd.randint(3600, 9 * 86400)),
                "premium": rnd.random() < .08,
                "spam": False,
                "password": rnd.random() < .3,
                "stars": rnd.choice([0, 0, 0, 0, 15, 50]),
                "gifts": rnd.choice([0, 0, 0, 1, 2]),
                "channels": rnd.randint(0, 6),
                "contacts": rnd.randint(0, 40),
                "dc": rnd.choice([1, 2, 4, 5]),
                "last_seen": int(time.time()) - rnd.randint(0, 20) * 86400,
                "session_days": rnd.randint(1, 400),
            })
    return out
