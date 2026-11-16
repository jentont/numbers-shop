"""HTTP: раздача Mini App и её API.

Каждый запрос подписан initData Telegram (заголовок X-Init-Data) —
подпись проверяется по токену бота, иначе 401. Для проверки без
Telegram есть DEV_AUTH=1 и ?dev=<id>, на проде его держать выключенным.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import time
from urllib.parse import parse_qsl

from aiohttp import web

import config
import crypto
import db
import i18n
import shop

log = logging.getLogger("numbers.web")
WEBAPP = config.BASE_DIR / "webapp"


def check_init_data(raw: str) -> dict | None:
    if not raw or not config.BOT_TOKEN:
        return None
    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received = pairs.pop("hash", "")
    if not received:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), received):
        return None
    if time.time() - int(pairs.get("auth_date") or 0) > 86400:
        return None
    try:
        return json.loads(pairs.get("user") or "{}")
    except ValueError:
        return None


_hits: dict[int, list[float]] = {}


def num(v, lo: float = 0, hi: float = 2 ** 53) -> int:
    """Целое из запроса в разумных пределах — иначе 400, а не падение базы."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text='{"error":"bad"}', content_type="application/json")
    if not math.isfinite(f) or f < lo or f > hi:
        raise web.HTTPBadRequest(text='{"error":"bad"}', content_type="application/json")
    return int(f)


def money_in(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) and 0 < f < 1_000_000 else 0.0


async def _user_nogate(req: web.Request) -> dict:
    return await _user(req, gate_check=False)


async def _user(req: web.Request, gate_check: bool = True) -> dict:
    tg = check_init_data(req.headers.get("X-Init-Data", ""))
    # Вход без подписи Telegram — только для локальной проверки. Если задан
    # боевой https-адрес, DEV_AUTH игнорируется, даже если его забыли выключить.
    if tg is None and config.DEV_AUTH and not config.webapp_enabled():
        dev = req.headers.get("X-Dev") or req.query.get("dev") or ""
        if dev.isdigit():
            tg = {"id": int(dev), "first_name": f"Dev {dev}", "username": f"dev{dev}", "language_code": "ru"}
    if not tg or not tg.get("id"):
        raise web.HTTPUnauthorized(text=json.dumps({"error": "auth"}), content_type="application/json")
    uid = int(tg["id"])
    now = time.time()
    hits = [t for t in _hits.get(uid, []) if now - t < 60]
    if len(hits) >= 150:
        raise web.HTTPTooManyRequests(text='{"error":"slow_down"}', content_type="application/json")
    hits.append(now)
    _hits[uid] = hits
    import gate
    if (gate_check and gate.active() and uid not in config.ADMIN_IDS and req.path not in ("/api/me", "/api/lang")
            and not await shop.is_subscribed(uid)):
        raise web.HTTPForbidden(text=json.dumps({"error": "need_sub", "channel": config.CHANNEL_URL}),
                                content_type="application/json")
    if len(_hits) > 100_000:
        _hits.clear()
    u = await db.get_user(int(tg["id"]))
    if u is None:
        u = await db.touch_user(int(tg["id"]), tg.get("first_name", ""), tg.get("username", ""))
        await db.set_lang(int(tg["id"]), i18n.pick(tg.get("language_code")))
        u = await db.get_user(int(tg["id"]))
    return dict(u)


def ok(data) -> web.Response:
    return web.json_response(data, dumps=lambda x: json.dumps(x, ensure_ascii=False))


def err(code: str, status: int = 400, **extra) -> web.Response:
    return web.json_response({"error": code, **extra}, status=status)


async def _body(req: web.Request) -> dict:
    try:
        data = await req.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


# ── Маршруты ──────────────────────────────────────────────────────────

async def me(req):
    u = await _user(req)
    return ok({
        "id": u["id"], "name": u["name"], "lang": i18n.pick(u["lang"]), "balance": u["kop"],
        "tour_done": bool(u["tour_done"]), "brand": config.BRAND, "methods": crypto.methods(),
        "star_rub": config.STAR_RUB, "stars_markup": config.STARS_MARKUP, "topup_min": config.TOPUP_MIN,
        "channel": config.CHANNEL_URL, "support": config.SUPPORT.lstrip("@"), "markup": config.MARKUP,
        "bot": config.BOT_USERNAME, "demo": config.LZT_DEMO, "terms_ok": bool(u["terms_at"]),
        "banned": bool(u["banned"]), "max_per_day": config.MAX_PER_DAY,
        "need_sub": await _need_sub(u["id"]), "channel_name": config.CHANNEL,
    })


async def _need_sub(uid: int) -> bool:
    import gate
    if not gate.active() or uid in config.ADMIN_IDS:
        return False
    return not await shop.is_subscribed(uid)


async def recheck_sub(req):
    u = await _user_nogate(req)
    shop.forget_sub(u["id"])
    need = await _need_sub(u["id"])
    if not need:
        await shop.ref_subscribed(u["id"])
    return ok({"need_sub": need})


async def accept(req):
    u = await _user(req)
    await db.accept_terms(u["id"])
    return ok({"ok": True})


async def set_lang(req):
    u = await _user(req)
    lang = str((await _body(req)).get("lang") or "")
    if lang in i18n.LANGS:
        await db.set_lang(u["id"], lang)
    return ok({"lang": i18n.pick(lang)})


async def tour_done(req):
    u = await _user(req)
    await db.run("UPDATE users SET tour_done=1 WHERE id=?", (u["id"],))
    return ok({"ok": True})


async def home(req):
    await _user(req)
    return ok(await shop.home())


async def lots(req):
    await _user(req)
    q = req.query
    f = {k: q.get(k) for k in ("sort", "pmin", "pmax", "origin")}
    for k in ("premium", "nopass", "fresh"):
        f[k] = q.get(k) == "1"
    try:
        items = await shop.lots(q.get("country", "").upper(), f)
    except Exception as exc:  # noqa: BLE001 — LZT недоступен
        log.warning("лоты: %s", exc)
        return err("market_down", 503)
    return ok({"items": items})


async def buy(req):
    u = await _user(req)
    b = await _body(req)
    try:
        if b.get("instant"):
            order = await shop.buy_instant(u["id"], str(b["instant"]).upper())
        else:
            order = await shop.buy_lot(u["id"], num(b.get("item_id") or 0), num(b.get("price") or 0))
    except shop.ShopError as exc:
        return err(exc.code, **exc.extra)
    except (TypeError, ValueError):
        return err("bad")
    return ok({"order": order, "balance": (await db.get_user(u["id"]))["kop"]})


async def orders(req):
    u = await _user(req)
    return ok({"items": [await shop.order_view(o) for o in await db.user_orders(u["id"])]})


async def order(req):
    u = await _user(req)
    o = await db.get_order(num(req.match_info["oid"]))
    if o is None or int(o["user_id"]) != u["id"]:
        return err("not_found", 404)
    return ok({"order": await shop.order_view(o), "balance": (await db.get_user(u["id"]))["kop"]})


async def code(req):
    u = await _user(req)
    try:
        got = await shop.get_code(u["id"], num((await _body(req)).get("order") or 0))
    except shop.ShopError as exc:
        return err(exc.code)
    return ok(got)


async def topup(req):
    u = await _user(req)
    b = await _body(req)
    try:
        inv = await crypto.create(u["id"], str(b.get("provider") or "")[:16], money_in(b.get("rub")))
    except crypto.PayError as exc:
        return err(str(exc))
    except (TypeError, ValueError):
        return err("bad")
    if inv["provider"] != "stars":
        asyncio.create_task(crypto.watch(inv["invoice_id"]))
    return ok(inv)


async def invoice(req):
    u = await _user(req)
    row = await db.get_invoice(num(req.match_info["iid"]))
    if row is None or int(row["user_id"]) != u["id"]:
        return err("not_found", 404)
    if row["status"] == "new" and row["provider"] != "stars" and await crypto.check_one(int(row["id"])):
        await crypto.credit(int(row["id"]))
        row = await db.get_invoice(int(row["id"]))
    return ok({"status": row["status"], "balance": (await db.get_user(u["id"]))["kop"]})


async def history(req):
    u = await _user(req)
    per = 10
    try:
        page = max(0, min(100_000, int(req.query.get("page") or 0)))
    except ValueError:
        page = 0
    return ok({"items": await db.history(u["id"], per, page * per), "total": await db.history_count(u["id"]), "per": per})


async def legal(req):
    """Условия и политика отдельной страницей — ссылку можно дать в BotFather."""
    kind = req.match_info["kind"]
    lang = "ru" if req.query.get("lang", "ru") == "ru" else "en"
    body = (WEBAPP / "legal" / f"{kind}.{lang}.html").read_text(encoding="utf-8")
    page = ('<!doctype html><html lang="%s"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>%s</title><link rel="stylesheet" href="/static/styles.css">'
            '</head><body><main class="legal legal-page">%s</main></body></html>') % (lang, config.BRAND, body)
    return web.Response(text=page, content_type="text/html")


async def transfer(req):
    u = await _user(req)
    b = await _body(req)
    try:
        res = await shop.transfer(u["id"], str(b.get("to") or ""), int(round(money_in(b.get("rub")) * 100)))
    except shop.ShopError as exc:
        return err(exc.code, **exc.extra)
    return ok({"balance": (await db.get_user(u["id"]))["kop"], "to": res["to"]})


async def promo(req):
    u = await _user(req)
    try:
        got = await shop.promo(u["id"], str((await _body(req)).get("code") or ""))
    except shop.ShopError as exc:
        return err(exc.code)
    return ok({"amount": got, "balance": (await db.get_user(u["id"]))["kop"]})


async def report(req):
    u = await _user(req)
    try:
        res = await shop.report(u["id"], num((await _body(req)).get("order") or 0))
    except shop.ShopError as exc:
        return err(exc.code)
    return ok({**res, "balance": (await db.get_user(u["id"]))["kop"]})


async def ref(req):
    u = await _user(req)
    return ok(await shop.ref_state(u["id"]))


async def ref_claim(req):
    u = await _user(req)
    try:
        order = await shop.ref_claim(u["id"])
    except shop.ShopError as exc:
        return err(exc.code, **exc.extra)
    return ok({"order": order, "state": await shop.ref_state(u["id"])})


async def giveaway(req):
    u = await _user(req)
    return ok(await shop.giveaway_state(u["id"]))


async def giveaway_join(req):
    u = await _user(req)
    try:
        return ok(await shop.giveaway_join(u["id"]))
    except shop.ShopError as exc:
        return err(exc.code, **exc.extra)


async def index(req):
    resp = web.FileResponse(WEBAPP / "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def app() -> web.Application:
    a = web.Application(client_max_size=64 * 1024)
    r = a.router
    r.add_get("/", index)
    r.add_get("/health", lambda req: web.Response(text="ok"))  # проверка для хостинга, без авторизации
    r.add_get("/api/me", me)
    r.add_post("/api/lang", set_lang)
    r.add_post("/api/tour", tour_done)
    r.add_post("/api/accept", accept)
    r.add_post("/api/sub", recheck_sub)
    r.add_get("/{kind:terms|privacy}", legal)
    r.add_get("/api/home", home)
    r.add_get("/api/lots", lots)
    r.add_post("/api/buy", buy)
    r.add_get("/api/orders", orders)
    r.add_get("/api/order/{oid:\\d+}", order)
    r.add_post("/api/code", code)
    r.add_post("/api/topup", topup)
    r.add_get("/api/invoice/{iid:\\d+}", invoice)
    r.add_get("/api/history", history)
    r.add_post("/api/transfer", transfer)
    r.add_post("/api/promo", promo)
    r.add_post("/api/report", report)
    r.add_get("/api/ref", ref)
    r.add_post("/api/ref/claim", ref_claim)
    r.add_get("/api/giveaway", giveaway)
    r.add_post("/api/giveaway/join", giveaway_join)
    r.add_static("/static/", WEBAPP, show_index=False)
    return a
