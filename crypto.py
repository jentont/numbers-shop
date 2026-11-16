"""Пополнение баланса: CryptoBot (@send), xRocket, TON в Tonkeeper и Telegram Stars.

Логика взята из nakrutkabot и проверена там на живых деньгах:
счёт выставляется в рублях, сумма в крипте — по живому курсу, деньги
зачисляются только после того, как оплату подтвердил API провайдера.
Двойного зачисления нет: db.pay_invoice переводит счёт new → paid одним
UPDATE с условием на статус.

Звёзды дороже в STARS_MARKUP раз (по умолчанию ×2): выводятся они
только через 21 день и по курсу ниже покупного.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

import aiohttp

import config
import db

log = logging.getLogger("numbers.crypto")

TIMEOUT = aiohttp.ClientTimeout(total=25)
TITLES = {"cryptobot": "CryptoBot (Send)", "xrocket": "xRocket", "ton": "Tonkeeper (TON)", "stars": "Telegram Stars"}

_session: aiohttp.ClientSession | None = None
_rates: dict[str, tuple[float, float]] = {}
RATE_TTL = 300


class PayError(RuntimeError):
    pass


async def _sess() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=TIMEOUT)
    return _session


async def close() -> None:
    if _session is not None and not _session.closed:
        await _session.close()


async def _json(method: str, url: str, **kw) -> Any:
    sess = await _sess()
    async with sess.request(method, url, **kw) as resp:
        text = await resp.text()
        try:
            return await resp.json(content_type=None)
        except Exception as exc:  # noqa: BLE001
            raise PayError(f"{url}: не JSON ({resp.status}) {text[:160]}") from exc


async def rate_rub(asset: str) -> float:
    asset = asset.upper()
    got = _rates.get(asset)
    if got and time.time() - got[1] < RATE_TTL:
        return got[0]
    value = 0.0
    if config.CRYPTOBOT_TOKEN:
        try:
            for item in await _cryptobot("getExchangeRates") or []:
                if str(item.get("source", "")).upper() == asset and str(item.get("target", "")).upper() == "RUB":
                    value = float(item.get("rate") or 0)
                    break
        except Exception as exc:  # noqa: BLE001
            log.debug("курс CryptoBot: %s", exc)
    if value <= 0:
        try:
            token = "ton" if asset == "TON" else asset.lower()
            payload = await _json("GET", f"{config.TONAPI_URL}/v2/rates",
                                  params={"tokens": token, "currencies": "rub"})
            for key in (asset, token.upper(), token):
                got = (payload.get("rates") or {}).get(key)
                if isinstance(got, dict):
                    value = float((got.get("prices") or {}).get("RUB") or 0)
                    if value:
                        break
        except Exception as exc:  # noqa: BLE001
            log.debug("курс tonapi: %s", exc)
    if value <= 0:
        value = config.TON_RUB if asset == "TON" else config.USDT_RUB
        log.warning("курс %s взят из .env: %.2f ₽", asset, value)
    _rates[asset] = (value, time.time())
    return value


# ── CryptoBot ─────────────────────────────────────────────────────────

async def _cryptobot(method: str, **params) -> Any:
    if not config.CRYPTOBOT_TOKEN:
        raise PayError("CRYPTOBOT_TOKEN не задан")
    base = "https://testnet-pay.crypt.bot/api" if config.CRYPTOBOT_TESTNET else "https://pay.crypt.bot/api"
    payload = await _json("POST", f"{base}/{method}", headers={"Crypto-Pay-API-Token": config.CRYPTOBOT_TOKEN},
                          json={k: v for k, v in params.items() if v is not None})
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise PayError(str((payload or {}).get("error") or payload)[:200])
    return payload.get("result")


async def _create_cryptobot(inv_id: int, rub: float):
    asset = config.CRYPTOBOT_ASSET
    rate = await rate_rub(asset)
    amount = round(rub / rate, 6)
    r = await _cryptobot("createInvoice", asset=asset, amount=f"{amount:.6f}",
                         description=f"{config.BRAND}: пополнение на {rub:.0f} ₽", payload=str(inv_id),
                         expires_in=config.INVOICE_TTL_MIN * 60, allow_comments=False, allow_anonymous=True)
    url = r.get("mini_app_invoice_url") or r.get("bot_invoice_url") or r.get("pay_url") or ""
    return str(r.get("invoice_id")), url, asset, amount, rate


async def _check_cryptobot(rows: list) -> set[int]:
    ids = [str(r["external_id"]) for r in rows if r["external_id"]]
    paid: set[int] = set()
    for i in range(0, len(ids), 100):
        result = await _cryptobot("getInvoices", invoice_ids=",".join(ids[i:i + 100]))
        items = result.get("items") if isinstance(result, dict) else result
        for it in items or []:
            raw = str(it.get("payload") or "").strip()
            if str(it.get("status")) == "paid" and raw.isdigit():
                paid.add(int(raw))
    return paid


# ── xRocket ───────────────────────────────────────────────────────────

async def _xrocket(method: str, path: str, **kw) -> Any:
    if not config.XROCKET_TOKEN:
        raise PayError("XROCKET_TOKEN не задан")
    base = "https://dev-pay.xrocket.tg" if config.XROCKET_TESTNET else "https://pay.xrocket.tg"
    payload = await _json(method, f"{base}{path}", headers={"Rocket-Pay-Key": config.XROCKET_TOKEN}, **kw)
    if isinstance(payload, dict) and payload.get("success") is False:
        raise PayError(str(payload.get("message") or payload)[:200])
    return payload.get("data") if isinstance(payload, dict) else payload


async def _create_xrocket(inv_id: int, rub: float):
    asset = config.XROCKET_ASSET
    rate = await rate_rub(asset)
    amount = round(rub / rate, 6)
    d = await _xrocket("POST", "/tg-invoices", json={
        "amount": amount, "numPayments": 1, "currency": asset,
        "description": f"{config.BRAND}: пополнение на {rub:.0f} ₽",
        "payload": str(inv_id), "expiredIn": config.INVOICE_TTL_MIN * 60,
    }) or {}
    return str(d.get("id") or ""), str(d.get("link") or d.get("payUrl") or ""), asset, amount, rate


def _xrocket_paid(d) -> bool:
    """Только статус paid от самого xRocket. totalActivations — это НЕ оплаты."""
    d = d or {}
    if str(d.get("status") or "").lower() != "paid":
        return False
    total = int(d.get("totalActivations") or 1)
    left = int(d.get("activationsLeft") if d.get("activationsLeft") is not None else 0)
    return left < total


async def _check_xrocket(rows: list) -> set[int]:
    paid: set[int] = set()
    for row in rows:
        if not row["external_id"]:
            continue
        try:
            if _xrocket_paid(await _xrocket("GET", f"/tg-invoices/{row['external_id']}")):
                paid.add(int(row["id"]))
        except PayError as exc:
            log.debug("xRocket %s: %s", row["external_id"], exc)
    return paid


# ── TON (Tonkeeper) ───────────────────────────────────────────────────

def ton_comment(inv_id: int) -> str:
    return f"sn{inv_id}"


async def _create_ton(inv_id: int, rub: float):
    rate = await rate_rub("TON")
    amount = round(rub / rate, 4)
    url = (f"https://app.tonkeeper.com/transfer/{config.TON_WALLET}"
           f"?amount={int(amount * 1e9)}&text={ton_comment(inv_id)}")
    return "", url, "TON", amount, rate


async def _check_ton(rows: list) -> set[int]:
    if not config.TON_WALLET:
        return set()
    headers = {"X-API-Key": config.TONCENTER_KEY} if config.TONCENTER_KEY else {}
    try:
        payload = await _json("GET", f"{config.TONCENTER_URL}/transactions", headers=headers,
                              params={"account": config.TON_WALLET, "limit": 100, "sort": "desc"})
    except PayError as exc:
        log.debug("toncenter: %s", exc)
        return set()
    got: dict[str, int] = {}
    for tx in (payload or {}).get("transactions") or []:
        msg = tx.get("in_msg") or {}
        comment = str(((msg.get("message_content") or {}).get("decoded") or {}).get("comment") or "").strip()
        if comment:
            try:
                got[comment] = max(got.get(comment, 0), int(msg.get("value") or 0))
            except (TypeError, ValueError):
                pass
    paid = set()
    for row in rows:
        nano = got.get(row["comment"] or ton_comment(int(row["id"])))
        if nano is not None and nano >= int(float(row["amount"]) * 1e9 * config.PAY_TOLERANCE):
            paid.add(int(row["id"]))
    return paid


CREATORS = {"cryptobot": _create_cryptobot, "xrocket": _create_xrocket, "ton": _create_ton}
CHECKERS = {"cryptobot": _check_cryptobot, "xrocket": _check_xrocket, "ton": _check_ton}


def methods() -> list[dict]:
    out = [{"id": p, "title": TITLES[p]} for p in config.crypto_providers()]
    if config.STARS_ON:
        out.append({"id": "stars", "title": TITLES["stars"], "markup": config.STARS_MARKUP})
    return out


async def create(uid: int, provider: str, rub: float) -> dict:
    rub = float(rub)
    if not math.isfinite(rub):
        raise PayError("bad")
    rub = round(rub, 2)
    opened = await db.one("SELECT COUNT(*) n FROM invoices WHERE user_id=? AND status='new' AND created_at>?",
                          (uid, int(time.time()) - config.INVOICE_TTL_MIN * 60))
    if opened["n"] >= 5:
        raise PayError("too_many")
    if rub < config.TOPUP_MIN:
        raise PayError(f"min:{config.TOPUP_MIN:.0f}")
    if rub > 100_000:
        raise PayError("max")
    kop = int(round(rub * 100))
    if provider == "stars":
        import shop as _shop
        if not config.STARS_ON or _shop.bot is None:
            raise PayError("off")
        import shop
        from aiogram.types import LabeledPrice
        stars = shop.stars_for(kop)
        inv_id = await db.create_invoice(uid, "stars", kop)
        link = await shop.bot.create_invoice_link(
            title=f"{config.BRAND}", description=f"Пополнение баланса на {rub:.0f} ₽",
            payload=f"inv:{inv_id}", currency="XTR", prices=[LabeledPrice(label="Баланс", amount=stars)],
        )
        await db.update_invoice(inv_id, asset="XTR", amount=stars, pay_url=link, external_id=f"s{inv_id}")
        return {"invoice_id": inv_id, "provider": "stars", "pay_url": link, "asset": "XTR",
                "amount": stars, "rub": rub, "title": TITLES["stars"]}
    if provider not in CREATORS or provider not in config.crypto_providers():
        raise PayError("off")
    inv_id = await db.create_invoice(uid, provider, kop)
    try:
        ext, url, asset, amount, rate = await CREATORS[provider](inv_id, rub)
    except Exception as exc:  # noqa: BLE001
        await db.update_invoice(inv_id, status="expired")
        log.warning("счёт #%s (%s) не выставлен: %s", inv_id, provider, exc)
        raise PayError("provider") from exc
    await db.update_invoice(inv_id, asset=asset, amount=amount, rate=rate, pay_url=url,
                            external_id=ext or str(inv_id),
                            comment=ton_comment(inv_id) if provider == "ton" else "")
    return {"invoice_id": inv_id, "provider": provider, "pay_url": url, "asset": asset, "amount": amount,
            "rub": rub, "title": TITLES[provider], "wallet": config.TON_WALLET if provider == "ton" else "",
            "comment": ton_comment(inv_id) if provider == "ton" else ""}


async def check_one(inv_id: int) -> bool:
    row = await db.get_invoice(inv_id)
    if row is None or row["status"] != "new":
        return bool(row and row["status"] == "paid")
    checker = CHECKERS.get(row["provider"])
    if checker is None:
        return False
    try:
        return int(row["id"]) in await checker([row])
    except Exception as exc:  # noqa: BLE001
        log.debug("проверка #%s: %s", inv_id, exc)
        return False


async def credit(inv_id: int) -> bool:
    got = await db.pay_invoice(inv_id)
    if got is None:
        return False
    uid, kop = got
    row = await db.get_invoice(inv_id)
    import shop
    log.info("счёт #%s оплачен: +%s для %s", inv_id, kop, uid)
    await shop.notify(uid, "topup", amount=shop.money(kop))
    await shop._admin_note(f"💳 Пополнение +{shop.money(kop)} · {TITLES.get(row['provider'])}\n"  # noqa: SLF001
                           f"{await shop.who(uid)}")
    return True


async def poll() -> int:
    rows = await db.open_invoices()
    n = 0
    for provider, checker in CHECKERS.items():
        batch = [r for r in rows if r["provider"] == provider]
        if not batch or provider not in config.crypto_providers():
            continue
        try:
            for inv_id in await checker(batch):
                n += await credit(inv_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("проверка %s: %s", provider, exc)
    await db.expire_invoices(int(time.time()) - config.INVOICE_TTL_MIN * 60)
    return n


async def watch(inv_id: int, tries: int = 20, delay: int = 12) -> None:
    """Частые проверки сразу после выставления — человек ждёт у экрана."""
    for _ in range(tries):
        await asyncio.sleep(delay)
        row = await db.get_invoice(inv_id)
        if row is None or row["status"] != "new":
            return
        if await check_one(inv_id):
            await credit(inv_id)
            return
