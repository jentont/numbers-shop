"""Админ-панель Solutions Numbers: всё управление магазином кнопками.

/admin открывает панель — одно сообщение, которое редактируется на месте.
Все списки листаются страницами, длинных простыней нет.

Разделы: сводка, люди (поиск, карточка, баланс, бан, доверенный, история,
пополнения, покупки, рефералы, написать), заказы, рассылка (текст, медиа,
альбомы, кнопки со стилем и премиум-иконкой), главное меню (медиа, текст,
стиль кнопки), настройки (config.EDITABLE), промокоды и скидки по странам,
инструменты (конкурс, резерв, эмодзи, LZT, выгрузка CSV).

Безопасность: каждый callback (префикс ap:) заново проверяет, что нажал
админ; все поля callback_data разбираются защитно (их можно подделать);
всё, что пришло от людей (имена, ники, коды, причины), экранируется.

Ожидание ввода (поиск, сумма, причина бана, значение настройки, рассылка,
медиа меню…) хранится в памяти по id админа и живёт 10 минут. Обработчик
сообщений срабатывает только при активном ожидании у админа, поэтому
обычные сообщения людей он не трогает.

Эмодзи — только премиум: тексты через b._e(), кнопки через b._btn().
Кнопки без иконки (листание, фильтры) — чистый текст без эмодзи.
"""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import html
import io
import logging
import re
import time
from typing import Any, Awaitable, Callable

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter,
)
from aiogram.filters import Command, Filter
from aiogram.types import (
    BufferedInputFile, CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

import bot as b
import config
import countries
import db
import emoji
import lzt
import shop

log = logging.getLogger("numbers.admin")
router = Router(name="adminpanel")

PER = 8                      # строк на странице
WAIT_TTL = 600               # ожидание ввода живёт 10 минут
SEP = "─" * 22
MSK = dt.timezone(dt.timedelta(hours=3))

#: Ожидание ввода: id админа → {"kind", "ts", "back", ...}.
WAIT: dict[int, dict[str, Any]] = {}
#: Последнее сообщение панели у админа: id админа → (chat_id, message_id).
PANEL: dict[int, tuple[int, int]] = {}
#: Куда возвращаться из карточек: id админа → {"ul": ..., "ol": ...}.
CTX: dict[int, dict[str, str]] = {}
#: Черновик рассылки: id админа → {"chat", "ids", "album", "kb", "what"}.
DRAFT: dict[int, dict[str, Any]] = {}
#: Части альбома, пока они долетают: (id админа, media_group_id) → [message_id].
_ALBUM: dict[tuple[int, str], list[int]] = {}
_ALBUM_TASK: dict[tuple[int, str], asyncio.Task] = {}
#: Текущая рассылка (одна на весь бот).
BC: dict[str, Any] = {}
BC_TASK: asyncio.Task | None = None
_ANSWERED: set[str] = set()
NL = 10  # байт перевода строки — для подсчёта строк CSV

_trusted_ok = False
_lzt_cache: tuple[float, float | None] = (0.0, None)


# ── Мелочи оформления ─────────────────────────────────────────────────

def h(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=False)


def is_admin(uid: int | None) -> bool:
    return bool(uid) and uid in config.ADMIN_IDS


def head(ch: str, title: str) -> str:
    """Заголовок: премиум-эмодзи + жирный текст (без эмодзи, если набора нет)."""
    e = b._e(ch)  # noqa: SLF001
    return f"{e} <b>{title}</b>" if e else f"<b>{title}</b>"


def line(ch: str, text: str) -> str:
    e = b._e(ch)  # noqa: SLF001
    return f"{e} {text}" if e else text


def kv(rows: list[tuple[str, str]]) -> str:
    """Ровные строки «ключ  значение» моноширинным блоком."""
    w = max((len(k) for k, _ in rows), default=0)
    return "<pre>" + "\n".join(f"{h(k).ljust(w)}  {h(v)}" for k, v in rows) + "</pre>"


def ts(t: Any) -> str:
    try:
        t = int(t or 0)
    except (TypeError, ValueError):
        return "—"
    return dt.datetime.fromtimestamp(t, MSK).strftime("%d.%m.%y %H:%M") if t else "—"


def rub(kop: Any) -> str:
    return shop.money(int(kop or 0))


def rub_n(kop: Any) -> str:
    """Рубли без знака — для таблиц."""
    return f"{int(kop or 0) / 100:,.0f}".replace(",", " ")


def who(u: Any) -> str:
    """Имя и ник человека, экранированные."""
    if u is None:
        return "—"
    name = h(u["name"] or "").strip()
    nick = f"@{h(u['username'])}" if u["username"] else ""
    return " ".join(x for x in (name, nick) if x) or f"id {u['id']}"


def short(s: str, n: int = 24) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def bt(text: str, ch: str, cb: str | None = None, style: str | None = None, **kw) -> InlineKeyboardButton:
    """Кнопка с премиум-иконкой (через b._btn)."""
    if cb is not None:
        kw["callback_data"] = cb
    if style:
        kw["style"] = style
    return b._btn(text, ch, **kw)  # noqa: SLF001


def ib(text: str, cb: str, style: str | None = None) -> InlineKeyboardButton:
    """Кнопка без иконки — только текст без эмодзи (листание, фильтры)."""
    kw: dict[str, Any] = {"text": text, "callback_data": cb}
    if style:
        kw["style"] = style
    return InlineKeyboardButton(**kw)


def kb(*rows: list[InlineKeyboardButton] | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def home_btn() -> InlineKeyboardButton:
    return bt("Панель", "📊", "ap:home")


def back_row(back: str, label: str = "Назад") -> list[InlineKeyboardButton]:
    return [bt(label, "⬅️", back), home_btn()] if back != "ap:home" else [bt(label, "⬅️", back)]


def pager(prefix: str, page: int, pages: int) -> list[InlineKeyboardButton]:
    if pages <= 1:
        return []
    row = [ib("‹", f"{prefix}:{page - 1}") if page > 0 else ib("·", "ap:noop"),
           ib(f"{page + 1} / {pages}", "ap:noop"),
           ib("›", f"{prefix}:{page + 1}") if page < pages - 1 else ib("·", "ap:noop")]
    return row


def pages_of(total: int) -> int:
    return max(1, (total + PER - 1) // PER)


def clamp(page: int, total: int) -> int:
    return max(0, min(page, pages_of(total) - 1))


def to_int(s: Any, lo: int = 0, hi: int = 10 ** 15) -> int | None:
    """Защитный разбор числа из callback_data."""
    s = str(s)
    if not s or len(s) > 16 or not (s.isdigit() or (s[0] == "-" and s[1:].isdigit())):
        return None
    v = int(s)
    return v if lo <= v <= hi else None


def _plain(text: str) -> str:
    return re.sub(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', "", text)


def u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def today0() -> int:
    now = dt.datetime.now(MSK)
    return int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


Screen = tuple[str, InlineKeyboardMarkup]


# ── Показ панели ──────────────────────────────────────────────────────

async def _send(bot: Bot, chat_id: int, text: str, markup: InlineKeyboardMarkup | None) -> Message | None:
    for t in (text, _plain(text)):
        try:
            return await bot.send_message(chat_id, t, reply_markup=markup, parse_mode="HTML",
                                          disable_web_page_preview=True)
        except TelegramBadRequest as exc:
            log.debug("панель: %s", exc)
    return None


async def show(c: CallbackQuery, scr: Screen) -> None:
    """Редактирует сообщение панели; если это не текст — шлёт новое."""
    text, markup = scr
    aid = c.from_user.id
    msg = c.message
    if msg is not None and getattr(msg, "text", None):
        for t in (text, _plain(text)):
            try:
                await msg.edit_text(t, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
                PANEL[aid] = (msg.chat.id, msg.message_id)
                return
            except TelegramBadRequest as exc:
                if "not modified" in str(exc):
                    return
                log.debug("панель edit: %s", exc)
    sent = await _send(c.bot, aid, text, markup)
    if sent is not None:
        PANEL[aid] = (sent.chat.id, sent.message_id)


async def reply(m: Message, scr: Screen, note: str = "") -> None:
    """После ввода админа: новое сообщение панели внизу, старое (с вопросом) убираем."""
    text, markup = scr
    if note:
        text = f"{note}\n\n{text}"
    aid = m.from_user.id
    old = PANEL.pop(aid, None)
    sent = await _send(m.bot, m.chat.id, text, markup)
    if sent is not None:
        PANEL[aid] = (sent.chat.id, sent.message_id)
    if old and (sent is None or old != (sent.chat.id, sent.message_id)):
        try:
            await m.bot.delete_message(old[0], old[1])
        except TelegramAPIError:
            pass


def ask(aid: int, kind: str, back: str, text: str, extra: list | None = None, **data: Any) -> Screen:
    """Включает ожидание ввода и возвращает экран-вопрос с кнопкой «Отмена»."""
    WAIT[aid] = {"kind": kind, "ts": time.time(), "back": back, **data}
    rows = list(extra or [])
    rows.append([bt("Отмена", "⬅️", "ap:cancel")])
    return text, kb(*rows)


def ok_note(text: str) -> str:
    return line("✅", f"<b>{text}</b>")


def err_note(text: str) -> str:
    return line("🔔", f"<b>{text}</b>")


# ── Данные ────────────────────────────────────────────────────────────

async def has_trusted() -> bool:
    global _trusted_ok
    if not _trusted_ok:
        cols = {r[1] for r in await db.all_("PRAGMA table_info(users)")}
        _trusted_ok = "trusted" in cols
    return _trusted_ok


async def lzt_balance(fresh: bool = False) -> float | None:
    global _lzt_cache
    if not fresh and time.time() - _lzt_cache[0] < 60:
        return _lzt_cache[1]
    try:
        bal = await asyncio.wait_for(lzt.balance(), 8)
    except Exception as exc:  # noqa: BLE001
        log.info("баланс LZT: %s", exc)
        bal = None
    _lzt_cache = (time.time(), bal)
    return bal


async def period(since: int) -> dict[str, int]:
    s = await db.one("SELECT COUNT(*) n, COALESCE(SUM(price_kop),0) rev, COALESCE(SUM(cost_kop),0) cost "
                     "FROM orders WHERE status='done' AND source IN ('live','reserve') AND done_at>=?", (since,))
    p = {r["source"]: int(r["c"]) for r in await db.all_(
        "SELECT source, COALESCE(SUM(cost_kop),0) c FROM orders WHERE status='done' "
        "AND source IN ('giveaway','ref') AND done_at>=? GROUP BY source", (since,))}
    t = await db.one("SELECT COUNT(*) n, COALESCE(SUM(kop),0) s FROM invoices WHERE status='paid' AND paid_at>=?",
                     (since,))
    nu = await db.one("SELECT COUNT(*) n FROM users WHERE created_at>=?", (since,))
    margin = int(s["rev"]) - int(s["cost"])
    gw, rf = p.get("giveaway", 0), p.get("ref", 0)
    return {"orders": int(s["n"]), "rev": int(s["rev"]), "cost": int(s["cost"]), "margin": margin,
            "gw": gw, "ref": rf, "net": margin - gw - rf, "topups": int(t["s"]), "topups_n": int(t["n"]),
            "new": int(nu["n"])}


async def user_totals(uid: int) -> dict[str, int]:
    o = await db.one("SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN status='done' AND source IN ('live','reserve') "
                     "THEN price_kop ELSE 0 END),0) spent, COALESCE(SUM(status='done'),0) done "
                     "FROM orders WHERE user_id=?", (uid,))
    t = await db.one("SELECT COUNT(*) n, COALESCE(SUM(kop),0) s FROM invoices WHERE user_id=? AND status='paid'",
                     (uid,))
    r = await db.one("SELECT COUNT(*) n, COALESCE(SUM(ref_ok),0) ok FROM users WHERE ref_by=?", (uid,))
    return {"orders": int(o["n"]), "done": int(o["done"]), "spent": int(o["spent"]),
            "topups": int(t["s"]), "topups_n": int(t["n"]), "refs": int(r["n"]), "refs_ok": int(r["ok"])}


USER_FILTERS = {
    "all": ("Все", "1"),
    "bal": ("С балансом", "kop>0"),
    "buy": ("Покупатели", "id IN (SELECT user_id FROM orders WHERE status='done' AND source IN ('live','reserve'))"),
    "ban": ("Забанены", "banned!=''"),
    "tr": ("Доверенные", "trusted=1"),
}
ORDER_FILTERS = {
    "all": ("Все", "1"),
    "done": ("Выданы", "status='done'"),
    "pend": ("В работе", "status='pending'"),
    "refd": ("Возвраты", "status='refunded'"),
    "gw": ("Конкурс", "source='giveaway'"),
    "ref": ("Реф. призы", "source='ref'"),
}
STATUS = {"done": "выдан", "pending": "покупается", "refunded": "возврат"}
SOURCE = {"live": "маркет", "reserve": "резерв", "giveaway": "конкурс", "ref": "реф. приз"}
REASON = {"topup": "пополнение", "buy": "покупка", "refund": "возврат", "admin": "админ", "promo": "промокод",
          "send": "перевод", "receive": "перевод от друга"}
BC_TARGETS = {
    "all": ("Всем", "blocked=0"),
    "bal": ("С балансом", "blocked=0 AND kop>0"),
    "buy": ("Покупателям", "blocked=0 AND id IN (SELECT user_id FROM orders WHERE status='done' "
                           "AND source IN ('live','reserve'))"),
}
STYLES = [("", "обычная"), ("primary", "синяя"), ("success", "зелёная"), ("danger", "красная")]
TAG_STYLE = {"blue": "primary", "green": "success", "red": "danger"}

SETTING_INFO = {
    "MARKUP": "Наценка к цене LZT (0.10 = 10 %)",
    "MIN_MARGIN_RUB": "Минимум наценки с аккаунта, ₽",
    "STARS_MARKUP": "Множитель цены в звёздах",
    "STAR_RUB": "Номинал звезды, ₽",
    "RESERVE_SIZE": "Сколько аккаунтов держать в резерве",
    "RESERVE_MAX_PRICE": "Резерв: не дороже, ₽",
    "RESERVE_COUNTRIES": "Резерв: страны ISO-3 через запятую",
    "GIVEAWAY_ON": "Ежедневный конкурс",
    "GIVEAWAY_HOUR": "Час розыгрыша по МСК (0–23)",
    "GIVEAWAY_MAX_PRICE": "Приз конкурса: не дороже, ₽",
    "GIVEAWAY_BROADCAST": "Рассылка итогов конкурса",
    "REF_GOAL": "Друзей за один приз",
    "REF_PRIZE_MAX": "Реф. приз: не дороже, ₽",
    "REF_DAILY_MAX": "Реф. призов в сутки на всех",
    "MAX_PER_DAY": "Покупок в сутки на человека (0 — без лимита)",
    "MAX_PER_DAY_NEW": "Покупок в первые сутки (0 — без лимита)",
    "GUARANTEE_H": "Часов на жалобу «не работает»",
    "TOPUP_MIN": "Минимальное пополнение, ₽",
    "LZT_MAX_PRICE": "Дороже — не продаём, ₽",
    "CHANNEL": "Канал (@username)",
    "CHANNEL_URL": "Ссылка на канал",
    "SUPPORT": "Поддержка (@ник или ссылка)",
    "SUB_REQUIRED": "Обязательная подписка на канал",
}


def setting_names() -> list[str]:
    return list(config.EDITABLE)


def setting_value(name: str) -> str:
    v = getattr(config, name, None)
    kind = config.EDITABLE.get(name)
    if kind is bool:
        return "вкл" if v else "выкл"
    if kind is list:
        return ", ".join(v or []) or "—"
    if name in ("MAX_PER_DAY", "MAX_PER_DAY_NEW") and not v:
        return "без лимита"
    if kind is float:
        s = f"{float(v or 0):g}"
        return f"{s} ({float(v) * 100:g} %)" if name == "MARKUP" else s
    return str(v) if v not in (None, "") else "—"


# ── Сводка ────────────────────────────────────────────────────────────

async def v_home(aid: int) -> Screen:
    now = int(time.time())
    d, w, a = await period(today0()), await period(now - 7 * 86400), await period(0)
    rows = [("Выручка", "rev"), ("Закупка", "cost"), ("Маржа", "margin"), ("Конкурс", "gw"),
            ("Реф. призы", "ref"), ("Чистыми", "net"), ("Пополнено", "topups")]
    lw, cw = 11, 9
    tbl = ["₽".ljust(lw) + "Сегодня".rjust(cw) + "7 дней".rjust(cw) + "Всего".rjust(cw)]
    for label, key in rows:
        tbl.append(label.ljust(lw) + "".join(rub_n(p[key]).rjust(cw) for p in (d, w, a)))
    tbl.append("Продаж".ljust(lw) + "".join(str(p["orders"]).rjust(cw) for p in (d, w, a)))
    tbl.append("Новых людей".ljust(lw) + "".join(str(p["new"]).rjust(cw) for p in (d, w, a)))
    u = await db.one("SELECT COUNT(*) n, COALESCE(SUM(blocked=0),0) act, COALESCE(SUM(banned!=''),0) ban, "
                     "COALESCE(SUM(kop),0) bal, COALESCE(SUM(kop>0),0) withbal FROM users")
    r = await db.one("SELECT COUNT(*) n, COALESCE(SUM(cost_kop),0) c FROM reserve WHERE status='ready'")
    pend = await db.one("SELECT COUNT(*) n FROM orders WHERE status='pending'")
    bal = await lzt_balance()
    demo = " · демо" if config.LZT_DEMO else ""
    text = "\n".join([
        head("📊", f"{h(config.BRAND)} · панель{demo}"),
        SEP,
        f"<pre>{h(chr(10).join(tbl))}</pre>",
        line("💎", f"LZT: <b>{'нет ответа' if bal is None else rub(int(round(bal * 100)))}</b>"),
        line("📦", f"Резерв: <b>{r['n']}</b> шт на <b>{rub(r['c'])}</b>"),
        line("👥", f"Люди: <b>{u['n']}</b> · активны {u['act']} · забанены {u['ban']}"),
        line("👛", f"На балансах: <b>{rub(u['bal'])}</b> у {u['withbal']} чел."),
        line("⏰", f"Заказов в работе: <b>{pend['n']}</b>") if pend["n"] else "",
        SEP,
        f"Наценка {config.MARKUP * 100:g} % · звёзды ×{config.STARS_MARKUP:g} · обновлено {ts(now)[-5:]}",
    ]).replace("\n\n", "\n")
    running = bool(BC_TASK and not BC_TASK.done())
    markup = kb(
        [bt("Люди", "👥", "ap:u:all:0"), bt("Заказы", "📦", "ap:o:all:0")],
        [bt("Рассылка" + (" · идёт" if running else ""), "📢", "ap:b"), bt("Главное меню", "📱", "ap:m")],
        [bt("Настройки", "🔑", "ap:s:0"), bt("Промо", "🏷", "ap:p")],
        [bt("Инструменты", "🚀", "ap:t"), bt("Обновить", "✨", "ap:home")],
    )
    return text, markup


# ── Люди ──────────────────────────────────────────────────────────────

async def v_users(aid: int, flt: str, page: int) -> Screen:
    if flt not in USER_FILTERS:
        flt = "all"
    CTX.setdefault(aid, {})["ul"] = f"ap:u:{flt}:{page}"
    note = ""
    if flt == "tr" and not await has_trusted():
        where, note = "0", "\n<i>Колонки trusted ещё нет в базе.</i>"
    else:
        where = USER_FILTERS[flt][1]
    total = (await db.one(f"SELECT COUNT(*) n FROM users WHERE {where}"))["n"]
    page = clamp(page, total)
    CTX[aid]["ul"] = f"ap:u:{flt}:{page}"
    rows = await db.all_(f"SELECT * FROM users WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                         (PER, page * PER))
    lines = []
    for i, u in enumerate(rows, page * PER + 1):
        mark = " · бан" if u["banned"] else (" · ушёл" if u["blocked"] else "")
        lines.append(f"{i}. {who(u)} · <code>{u['id']}</code>\n    {rub(u['kop'])} · {ts(u['created_at'])}{mark}")
    text = "\n".join([head("👥", f"Люди · {USER_FILTERS[flt][0].lower()}"),
                      f"Всего: <b>{total}</b>{note}", SEP] + (lines or ["Пусто."]))
    chips = [ib(name, f"ap:u:{k}:0", "primary" if k == flt else None) for k, (name, _) in USER_FILTERS.items()]
    btns = [[bt(short(f"{u['name'] or u['username'] or u['id']}", 18) + f" · {rub(u['kop'])}", "👤", f"ap:uc:{u['id']}")]
            for u in rows]
    markup = kb(chips[:3], chips[3:], [bt("Поиск", "🔎", "ap:us")], *btns,
                pager(f"ap:u:{flt}", page, pages_of(total)), [home_btn()])
    return text, markup


async def v_user(aid: int, uid: int) -> Screen:
    u = await db.get_user(uid)
    if u is None:
        return f"{head('👤', 'Человек не найден')}\nID <code>{uid}</code> нет в базе.", kb(back_row("ap:u:all:0"))
    t = await user_totals(uid)
    trusted = None
    if await has_trusted():
        trusted = bool(u["trusted"])
    ref_line = "—"
    if u["ref_by"]:
        inviter = await db.get_user(int(u["ref_by"]))
        ref_line = f"{who(inviter)} · <code>{u['ref_by']}</code>"
    claimed = int(u["ref_used"] or 0) // max(1, config.REF_GOAL)
    limit = config.MAX_PER_DAY_NEW if time.time() - int(u["created_at"]) < 86400 else config.MAX_PER_DAY
    today = await db.bought_today(uid)
    info = kv([
        ("ID", str(uid)),
        ("Язык", u["lang"] or "—"),
        ("С нами с", ts(u["created_at"])),
        ("Баланс", rub(u["kop"])),
        ("Потратил", rub(t["spent"])),
        ("Пополнил", f"{rub(t['topups'])} ({t['topups_n']})"),
        ("Заказов", f"{t['orders']} (выдано {t['done']})"),
        ("Сегодня", f"{today} · " + ("без лимита" if trusted or not limit else f"лимит {limit}")),
        ("Друзей", f"{t['refs']} · засчитано {t['refs_ok']} · призов {claimed}"),
        ("Условия", ts(u["terms_at"]) if u["terms_at"] else "не приняты"),
        ("Бот", "заблокировал" if u["blocked"] else "активен"),
    ])
    status = []
    if u["banned"]:
        status.append(line("🛡", f"<b>Забанен:</b> {h(u['banned'])}"))
    if trusted:
        status.append(line("👑", "<b>Доверенный</b> — без суточного лимита"))
    nick = f"@{h(u['username'])}" if u["username"] else "без ника"
    text = "\n".join([head("👤", h(u["name"] or "Без имени")), f"{nick} · <code>{uid}</code>", SEP, info,
                      line("👥", f"Пригласил: {ref_line}"), *status])
    back = CTX.get(aid, {}).get("ul", "ap:u:all:0")
    tr_row = None
    if trusted is not None:
        tr_row = [bt("Доверенный: " + ("вкл" if trusted else "выкл"), "👑", f"ap:ut:{uid}",
                     "success" if trusted else None)]
    markup = kb(
        [bt("История", "📋", f"ap:uh:{uid}:0"), bt("Пополнения", "💳", f"ap:ui:{uid}:0")],
        [bt("Покупки", "🛒", f"ap:uo:{uid}:0"), bt("Рефералы", "👥", f"ap:ur:{uid}:0")],
        [bt("Начислить / списать", "🪙", f"ap:ub:{uid}")],
        [bt("Разбанить", "🛡", f"ap:uxu:{uid}", "success") if u["banned"]
         else bt("Забанить", "🛡", f"ap:ux:{uid}", "danger"),
         bt("Написать", "💬", f"ap:um:{uid}")],
        tr_row,
        [bt("Пригласивший", "👤", f"ap:uc:{u['ref_by']}")] if u["ref_by"] else None,
        back_row(back),
    )
    return text, markup


async def v_ledger(aid: int, uid: int, page: int) -> Screen:
    total = await db.history_count(uid)
    page = clamp(page, total)
    rows = await db.history(uid, PER, page * PER)
    lines = []
    for r in rows:
        sign = "+" if r["delta"] > 0 else ""
        ref = f" · {h(short(r['ref'], 20))}" if r["ref"] else ""
        lines.append(f"<code>{sign}{rub(r['delta'])}</code> {h(REASON.get(r['reason'], r['reason']))}{ref}\n"
                     f"    {ts(r['created_at'])}")
    u = await db.get_user(uid)
    text = "\n".join([head("📋", "История баланса"), f"{who(u)} · <code>{uid}</code> · записей {total}", SEP]
                     + (lines or ["Пусто."]))
    return text, kb(pager(f"ap:uh:{uid}", page, pages_of(total)), back_row(f"ap:uc:{uid}"))


async def v_invoices(aid: int, uid: int, page: int) -> Screen:
    total = (await db.one("SELECT COUNT(*) n FROM invoices WHERE user_id=?", (uid,)))["n"]
    page = clamp(page, total)
    rows = await db.all_("SELECT * FROM invoices WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                         (uid, PER, page * PER))
    st = {"new": "ждёт", "paid": "оплачен", "expired": "истёк"}
    lines = []
    for r in rows:
        amt = f" · {float(r['amount'] or 0):g} {h(r['asset'])}" if r["amount"] else ""
        lines.append(f"<code>#{r['id']}</code> {h(r['provider'])} · <b>{rub(r['kop'])}</b>{amt}\n"
                     f"    {st.get(r['status'], h(r['status']))} · {ts(r['paid_at'] or r['created_at'])}")
    u = await db.get_user(uid)
    text = "\n".join([head("💳", "Пополнения"), f"{who(u)} · <code>{uid}</code> · счетов {total}", SEP]
                     + (lines or ["Пусто."]))
    return text, kb(pager(f"ap:ui:{uid}", page, pages_of(total)), back_row(f"ap:uc:{uid}"))


def order_btn(o: Any) -> list[InlineKeyboardButton]:
    phone = o["phone"] or "без номера"
    return [bt(f"#{o['id']} · {o['country'] or '—'} · {short(phone, 14)} · {STATUS.get(o['status'], o['status'])}",
               "#️⃣", f"ap:oc:{o['id']}")]


async def v_user_orders(aid: int, uid: int, page: int) -> Screen:
    total = (await db.one("SELECT COUNT(*) n FROM orders WHERE user_id=?", (uid,)))["n"]
    page = clamp(page, total)
    CTX.setdefault(aid, {})["ol"] = f"ap:uo:{uid}:{page}"
    rows = await db.all_("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                         (uid, PER, page * PER))
    u = await db.get_user(uid)
    lines = [f"<code>#{o['id']}</code> {h(o['country'])} · <code>{h(o['phone'] or '—')}</code> · "
             f"{rub(o['price_kop'])} · {STATUS.get(o['status'], h(o['status']))}" for o in rows]
    text = "\n".join([head("🛒", "Покупки"), f"{who(u)} · <code>{uid}</code> · заказов {total}", SEP]
                     + (lines or ["Пусто."]))
    return text, kb(*[order_btn(o) for o in rows], pager(f"ap:uo:{uid}", page, pages_of(total)),
                    back_row(f"ap:uc:{uid}"))


async def v_refs(aid: int, uid: int, page: int) -> Screen:
    total = (await db.one("SELECT COUNT(*) n FROM users WHERE ref_by=?", (uid,)))["n"]
    page = clamp(page, total)
    rows = await db.all_("SELECT * FROM users WHERE ref_by=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                         (uid, PER, page * PER))
    u = await db.get_user(uid)
    lines = [f"{who(r)} · <code>{r['id']}</code> · {'засчитан' if r['ref_ok'] else 'не засчитан'}" for r in rows]
    text = "\n".join([head("👥", "Рефералы"), f"{who(u)} · <code>{uid}</code> · приглашено {total}", SEP]
                     + (lines or ["Пусто."]))
    btns = [[bt(short(r["name"] or r["username"] or str(r["id"]), 24), "👤", f"ap:uc:{r['id']}")] for r in rows]
    return text, kb(*btns, pager(f"ap:ur:{uid}", page, pages_of(total)), back_row(f"ap:uc:{uid}"))


async def search_users(q: str) -> tuple[list[Any], str]:
    """Человек по @нику, ID, номеру телефона или #заказу. Возвращает (люди, пояснение)."""
    q = q.strip()
    if not q:
        return [], ""
    if q.startswith("#") and q[1:].isdigit():
        o = await db.get_order(int(q[1:]))
        if o is None:
            return [], f"заказа {h(q)} нет"
        u = await db.get_user(int(o["user_id"]))
        return ([u] if u else []), f"покупатель заказа <code>{h(q)}</code>"
    digits = "".join(ch for ch in q if ch.isdigit())
    if q.startswith("+") or (digits and len(digits) >= 7 and re.fullmatch(r"[\d\s()+-]+", q)):
        if not q.startswith("+") and q.isdigit():
            u = await db.get_user(int(q))
            if u:
                return [u], "по ID"
        seen, out = set(), []
        for o in await db.whois(q):
            if o["user_id"] not in seen:
                seen.add(o["user_id"])
                u = await db.get_user(int(o["user_id"]))
                if u:
                    out.append(u)
        return out, f"по номеру <code>{h(q)}</code>"
    if q.isdigit():
        u = await db.get_user(int(q))
        return ([u] if u else []), "по ID"
    nick = q.lstrip("@")
    u = await db.one("SELECT * FROM users WHERE lower(username)=lower(?)", (nick,))
    if u:
        return [u], "по нику"
    like = f"%{nick.replace('%', '').replace('_', '')}%"
    rows = await db.all_("SELECT * FROM users WHERE username LIKE ? OR name LIKE ? ORDER BY created_at DESC LIMIT ?",
                         (like, like, PER))
    return rows, "по совпадению ника или имени"


def v_found(rows: list[Any], how: str, back: str) -> Screen:
    text = "\n".join([head("🔎", "Результаты поиска"), f"Найдено {len(rows)} · {how}", SEP]
                     + [f"{who(u)} · <code>{u['id']}</code> · {rub(u['kop'])}" for u in rows])
    btns = [[bt(short(u["name"] or u["username"] or str(u["id"]), 24), "👤", f"ap:uc:{u['id']}")] for u in rows]
    return text, kb(*btns, [bt("Искать ещё", "🔎", back)], [home_btn()])


# ── Заказы ────────────────────────────────────────────────────────────

async def v_orders(aid: int, flt: str, page: int) -> Screen:
    if flt not in ORDER_FILTERS:
        flt = "all"
    where = ORDER_FILTERS[flt][1]
    total = (await db.one(f"SELECT COUNT(*) n FROM orders WHERE {where}"))["n"]
    page = clamp(page, total)
    CTX.setdefault(aid, {})["ol"] = f"ap:o:{flt}:{page}"
    rows = await db.all_(f"SELECT * FROM orders WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?", (PER, page * PER))
    lines = [f"<code>#{o['id']}</code> {h(o['country'])} · {rub(o['price_kop'])} · "
             f"{STATUS.get(o['status'], h(o['status']))} · {ts(o['created_at'])}" for o in rows]
    text = "\n".join([head("📦", f"Заказы · {ORDER_FILTERS[flt][0].lower()}"), f"Всего: <b>{total}</b>", SEP]
                     + (lines or ["Пусто."]))
    chips = [ib(name, f"ap:o:{k}:0", "primary" if k == flt else None) for k, (name, _) in ORDER_FILTERS.items()]
    return text, kb(chips[:3], chips[3:], [bt("Поиск по номеру или #id", "🔎", "ap:os")],
                    *[order_btn(o) for o in rows], pager(f"ap:o:{flt}", page, pages_of(total)), [home_btn()])


async def v_order(aid: int, oid: int) -> Screen:
    o = await db.get_order(oid)
    back = CTX.get(aid, {}).get("ol", "ap:o:all:0")
    if o is None:
        return f"{head('📦', 'Заказ не найден')}\n<code>#{oid}</code>", kb(back_row(back))
    u = await db.get_user(int(o["user_id"]))
    c3 = o["country"] or ""
    rows = [
        ("Статус", STATUS.get(o["status"], o["status"])),
        ("Откуда", SOURCE.get(o["source"], o["source"])),
        ("Страна", f"{c3} {countries.name_ru(c3)}" if c3 else "—"),
        ("Лот LZT", str(o["item_id"])),
        ("Закупка", rub(o["cost_kop"])),
        ("Цена", rub(o["price_kop"])),
        ("Маржа", rub(int(o["price_kop"]) - int(o["cost_kop"]))),
        ("Создан", ts(o["created_at"])),
        ("Закрыт", ts(o["done_at"])),
    ]
    extra = []
    if o["phone"]:
        extra.append(line("📱", f"Номер: <code>{h(o['phone'])}</code>"))
    if o["password"]:
        extra.append(line("🔒", f"2FA: <tg-spoiler><code>{h(o['password'])}</code></tg-spoiler>"))
    try:
        if o["reported"]:
            extra.append(line("🔔", "Покупатель жаловался «не работает»"))
    except (IndexError, KeyError):
        pass
    if o["error"]:
        extra.append(line("↩️", f"Ошибка: {h(short(o['error'], 200))}"))
    text = "\n".join([head("📦", f"Заказ #{oid}"), f"{who(u)} · <code>{o['user_id']}</code>", SEP, kv(rows), *extra])
    return text, kb([bt("Покупатель", "👤", f"ap:uc:{o['user_id']}")], back_row(back))


# ── Рассылка ──────────────────────────────────────────────────────────

def parse_buttons(text: str, entities: list | None) -> tuple[list[list[InlineKeyboardButton]], list[str]]:
    """Строки «Текст | ссылка #blue», в ряд через « ;; ». Премиум-эмодзи в начале → иконка кнопки."""
    icons = {e.offset: (e.length, e.custom_emoji_id) for e in (entities or [])
             if e.type == "custom_emoji" and e.custom_emoji_id}
    rows: list[list[InlineKeyboardButton]] = []
    errs: list[str] = []
    pos = 0
    for n, raw in enumerate(text.split("\n"), 1):
        start, pos = pos, pos + len(raw) + 1
        if not raw.strip():
            continue
        row = []
        off = 0
        for seg in raw.split(";;"):
            seg_at, off = start + off, off + len(seg) + 2
            item = seg.strip()
            if not item:
                continue
            at = seg_at + (len(seg) - len(seg.lstrip()))
            icon = None
            hit = icons.get(u16(text[:at]))
            if hit:
                need, k, units = hit[0], 0, 0
                while k < len(item) and units < need:
                    units += 2 if ord(item[k]) > 0xFFFF else 1
                    k += 1
                item, icon = item[k:].strip(), hit[1]
            m = re.match(r"^(?P<t>.+?)\s*\|\s*(?P<u>\S+)(?:\s+#(?P<s>blue|green|red))?\s*$", item, re.I)
            if not m:
                errs.append(f"строка {n}: нужно «Текст | ссылка»")
                continue
            label, url, tag = m["t"].strip(), m["u"], (m["s"] or "").lower()
            if not re.match(r"^(https?|tg)://\S+$", url, re.I):
                errs.append(f"строка {n}: ссылка должна начинаться с https:// или tg://")
                continue
            if not label or len(label) > 64:
                errs.append(f"строка {n}: текст кнопки 1–64 символа")
                continue
            kw: dict[str, Any] = {"text": label, "url": url}
            if icon:
                kw["icon_custom_emoji_id"] = icon
            if tag:
                kw["style"] = TAG_STYLE[tag]
            row.append(InlineKeyboardButton(**kw))
        if row:
            rows.append(row[:8])
    return rows[:20], errs


def bc_running() -> bool:
    return bool(BC_TASK and not BC_TASK.done())


async def bc_count(target: str) -> int:
    return int((await db.one(f"SELECT COUNT(*) n FROM users WHERE {BC_TARGETS[target][1]}"))["n"])


def bc_progress_text() -> str:
    done = BC.get("sent", 0) + BC.get("failed", 0) + BC.get("blocked", 0)
    total = max(1, BC.get("total", 0))
    pct = int(done * 100 / total)
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    state = "остановлена" if BC.get("stop") else ("закончена" if BC.get("finished") else "идёт")
    return "\n".join([
        head("📢", f"Рассылка {state}"), SEP,
        f"<code>{bar}</code> {pct} %",
        kv([("Кому", BC.get("target_name", "—")), ("Всего", str(BC.get("total", 0))),
            ("Отправлено", str(BC.get("sent", 0))), ("Не дошло", str(BC.get("failed", 0))),
            ("Заблокировали", str(BC.get("blocked", 0))), ("Начата", ts(BC.get("started")))]),
    ])


async def v_bc(aid: int) -> Screen:
    if bc_running():
        return bc_progress_text(), kb([bt("Обновить", "✨", "ap:bp"), bt("Остановить", "🛡", "ap:bstop", "danger")],
                                      [home_btn()])
    d = DRAFT.get(aid)
    if not d:
        return ask(aid, "bc", "ap:home", "\n".join([
            head("📢", "Рассылка"), SEP,
            "Пришлите сообщение, которое получат люди: текст с оформлением и премиум-эмодзи, "
            "фото, видео, GIF, файл или альбом.",
            "Потом можно добавить кнопки-ссылки и посмотреть, как это выглядит.",
        ]))
    return await v_bc_draft(aid)


async def v_bc_draft(aid: int, note: str = "") -> Screen:
    d = DRAFT.get(aid)
    if not d:
        return await v_bc(aid)
    nb = sum(len(r) for r in d["kb"].inline_keyboard) if d.get("kb") else 0
    counts = {k: await bc_count(k) for k in BC_TARGETS}
    text = "\n".join(x for x in [
        note,
        head("📢", "Черновик рассылки"), SEP,
        kv([("Что", d["what"]), ("Кнопок", str(nb) if nb else "нет")]),
        "<i>У альбома кнопки придут отдельным сообщением сразу после него.</i>" if d["album"] and nb else "",
        "Выше — предпросмотр ровно так, как увидят люди.",
        line("👥", f"Всем {counts['all']} · с балансом {counts['bal']} · покупателям {counts['buy']}"),
    ] if x)
    markup = kb(
        [bt("Кнопки" if not nb else "Изменить кнопки", "➕", "ap:bb"), bt("Предпросмотр", "🔎", "ap:bv")],
        [bt(f"Отправить всем · {counts['all']}", "🚀", "ap:bs:all", "primary")],
        [bt(f"С балансом · {counts['bal']}", "👛", "ap:bs:bal"), bt(f"Покупателям · {counts['buy']}", "🛒", "ap:bs:buy")],
        [bt("Отмена", "⬅️", "ap:bx")],
    )
    return text, markup


def _follow_text() -> str:
    return b._e("👇") or "<b>Ссылки</b>"  # noqa: SLF001


async def bc_deliver(bot: Bot, chat_id: int, d: dict) -> None:
    """Одна доставка черновика: копия (с форматированием и премиум-эмодзи) + кнопки."""
    if d["album"]:
        await bot.copy_messages(chat_id, d["chat"], d["ids"])
        if d.get("kb"):
            await bot.send_message(chat_id, _follow_text(), reply_markup=d["kb"], parse_mode="HTML")
    else:
        await bot.copy_message(chat_id, d["chat"], d["ids"][0], reply_markup=d.get("kb"))


async def bc_preview(bot: Bot, aid: int) -> str:
    d = DRAFT.get(aid)
    if not d:
        return ""
    try:
        await bc_deliver(bot, aid, d)
        return ""
    except TelegramAPIError as exc:
        return err_note(f"Telegram не принял: {h(exc)}")


async def _bc_edit(bot: Bot, final: bool = False) -> None:
    chat, mid = BC.get("chat"), BC.get("mid")
    if not chat or not mid:
        return
    markup = kb([home_btn()]) if final else kb([bt("Обновить", "✨", "ap:bp"),
                                                bt("Остановить", "🛡", "ap:bstop", "danger")])
    try:
        await bot.edit_message_text(text=bc_progress_text(), chat_id=chat, message_id=mid, reply_markup=markup,
                                    parse_mode="HTML")
    except TelegramAPIError as exc:
        log.debug("прогресс рассылки: %s", exc)


async def bc_run(bot: Bot, d: dict, ids: list[int]) -> None:
    try:
        for i, uid in enumerate(ids, 1):
            if BC.get("stop"):
                break
            for attempt in range(2):
                try:
                    await bc_deliver(bot, uid, d)
                    BC["sent"] += 1
                except TelegramRetryAfter as exc:
                    if attempt == 0:
                        await asyncio.sleep(min(int(exc.retry_after) + 1, 60))
                        continue
                    BC["failed"] += 1
                except TelegramForbiddenError:
                    BC["blocked"] += 1
                    await db.run("UPDATE users SET blocked=1 WHERE id=?", (uid,))
                except TelegramAPIError as exc:
                    BC["failed"] += 1
                    log.debug("рассылка %s: %s", uid, exc)
                except Exception as exc:  # noqa: BLE001 — рассылка не должна падать на одном человеке
                    BC["failed"] += 1
                    log.warning("рассылка %s: %s", uid, exc)
                break
            if i % 50 == 0:
                await _bc_edit(bot)
            await asyncio.sleep(0.05)
    finally:
        BC["finished"] = True
        await _bc_edit(bot, final=True)


async def bc_start(c: CallbackQuery, target: str) -> Screen | None:
    global BC_TASK
    aid = c.from_user.id
    d = DRAFT.get(aid)
    if bc_running():
        await say(c, "Рассылка уже идёт", show_alert=True)
        return await v_bc(aid)
    if not d:
        await say(c, "Черновик пропал — начните заново", show_alert=True)
        return await v_bc(aid)
    ids = [int(r["id"]) for r in await db.all_(f"SELECT id FROM users WHERE {BC_TARGETS[target][1]} ORDER BY id")]
    msg = c.message
    BC.clear()
    BC.update(sent=0, failed=0, blocked=0, total=len(ids), stop=False, finished=False, started=int(time.time()),
              target_name=BC_TARGETS[target][0], chat=msg.chat.id if msg else aid,
              mid=msg.message_id if msg and getattr(msg, "text", None) else None)
    DRAFT.pop(aid, None)
    BC_TASK = asyncio.create_task(bc_run(c.bot, dict(d), ids))
    await say(c, "Рассылка запущена")
    return bc_progress_text(), kb([bt("Обновить", "✨", "ap:bp"), bt("Остановить", "🛡", "ap:bstop", "danger")])


async def _album_done(bot: Bot, aid: int, chat_id: int, key: tuple[int, str]) -> None:
    await asyncio.sleep(1.5)
    ids = sorted(_ALBUM.pop(key, []))
    _ALBUM_TASK.pop(key, None)
    if not ids:
        return
    WAIT.pop(aid, None)
    DRAFT[aid] = {"chat": chat_id, "ids": ids[:10], "album": True, "kb": None, "what": f"альбом · {len(ids)} шт"}
    note = await bc_preview(bot, aid)
    text, markup = await v_bc_draft(aid, note)
    old = PANEL.pop(aid, None)
    sent = await _send(bot, aid, text, markup)
    if sent is not None:
        PANEL[aid] = (sent.chat.id, sent.message_id)
    if old:
        try:
            await bot.delete_message(old[0], old[1])
        except TelegramAPIError:
            pass


def msg_kind(m: Message) -> str:
    for attr, name in (("photo", "фото"), ("video", "видео"), ("animation", "GIF"), ("document", "файл"),
                       ("audio", "аудио"), ("voice", "голосовое"), ("video_note", "кружок"), ("sticker", "стикер"),
                       ("poll", "опрос")):
        if getattr(m, attr, None):
            return name + (" с подписью" if m.caption else "")
    return "текст"


# ── Главное меню ──────────────────────────────────────────────────────

MEDIA_NAME = {"photo": "фото", "animation": "GIF", "video": "видео", "none": "без медиа", "": "стандартный баннер"}


async def v_menu(aid: int, note: str = "") -> Screen:
    kind = await db.get_setting("menu_media_kind")
    mtext = await db.get_setting("menu_text")
    style = await db.get_setting("menu_button_style")
    sname = dict(STYLES).get(style, "обычная")
    warn = ""
    if mtext and kind != "none" and len(_visible(mtext)) > 1024:
        warn = err_note("Текст длиннее 1024 символов — с медиа он не влезет в подпись.")
    text = "\n".join(x for x in [
        note, head("📱", "Главное меню"), SEP,
        kv([("Медиа", MEDIA_NAME.get(kind, kind)), ("Текст", f"свой · {len(_visible(mtext))} симв." if mtext else
                                                    "стандартный"), ("Кнопка маркета", sname)]),
        warn,
        "Медиа: пришлите фото, GIF или видео. Текст: пришлите сообщение с оформлением — жирный, курсив, "
        "ссылки, спойлеры и премиум-эмодзи сохранятся.",
    ] if x)
    nxt = STYLES[(next((i for i, (k, _) in enumerate(STYLES) if k == style), 0) + 1) % len(STYLES)][0]
    markup = kb(
        [bt("Медиа", "📱", "ap:mm"), bt("Текст", "📋", "ap:mt")],
        [bt("Предпросмотр", "🔎", "ap:mp")],
        [bt(f"Кнопка: {sname}", "✨", f"ap:ms:{nxt or 'plain'}", style or None)],
        [bt("Без медиа", "📋", "ap:mn"), bt("Сбросить медиа", "↩️", "ap:mr:media")],
        [bt("Сбросить текст", "↩️", "ap:mr:text"), bt("Сбросить всё", "↩️", "ap:mr:all", "danger")],
        [home_btn()],
    )
    return text, markup


def _visible(html_text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", html_text or ""))


async def menu_preview(bot: Bot, aid: int, name: str) -> str:
    kind = await db.get_setting("menu_media_kind")
    fid = await db.get_setting("menu_media_id")
    text = await db.get_setting("menu_text")
    style = await db.get_setting("menu_button_style")
    u = await db.get_user(aid)
    if not text:
        try:
            text = b.menu_text("ru", name, int(u["kop"]) if u else 0)
        except Exception:  # noqa: BLE001
            text = h(config.BRAND)
    try:
        markup = b.menu_kb("ru")
        if style:
            rows = [[btn.model_copy(update={"style": style}) if btn.web_app else btn for btn in row]
                    for row in markup.inline_keyboard]
            markup = InlineKeyboardMarkup(inline_keyboard=rows)
    except Exception:  # noqa: BLE001
        markup = None
    try:
        if kind == "photo" and fid:
            await bot.send_photo(aid, fid, caption=text, reply_markup=markup, parse_mode="HTML")
        elif kind == "animation" and fid:
            await bot.send_animation(aid, fid, caption=text, reply_markup=markup, parse_mode="HTML")
        elif kind == "video" and fid:
            await bot.send_video(aid, fid, caption=text, reply_markup=markup, parse_mode="HTML")
        elif kind == "none":
            await bot.send_message(aid, text, reply_markup=markup, parse_mode="HTML")
        elif b.BANNER.exists():
            await bot.send_photo(aid, FSInputFile(b.BANNER), caption=text, reply_markup=markup, parse_mode="HTML")
        else:
            await bot.send_message(aid, text, reply_markup=markup, parse_mode="HTML")
    except TelegramAPIError as exc:
        return err_note(f"Предпросмотр не отправился: {h(exc)}")
    return ""


# ── Настройки ─────────────────────────────────────────────────────────

async def v_settings(aid: int, page: int, note: str = "") -> Screen:
    names = setting_names()
    page = clamp(page, len(names))
    CTX.setdefault(aid, {})["sp"] = str(page)
    chunk = list(enumerate(names))[page * PER:(page + 1) * PER]
    rows = [(n, setting_value(n)) for _, n in chunk]
    text = "\n".join(x for x in [note, head("🔑", "Настройки"), "Применяются сразу и сохраняются в базе.", SEP,
                                 kv(rows), "Нажмите на настройку, чтобы изменить. Переключатели меняются сразу."] if x)
    btns = []
    for i, n in chunk:
        kind = config.EDITABLE[n]
        if kind is bool:
            on = bool(getattr(config, n, False))
            btns.append([bt(f"{n}: {'вкл' if on else 'выкл'}", "🔑", f"ap:se:{i}", "success" if on else None)])
        else:
            btns.append([bt(f"{n} = {short(setting_value(n), 18)}", "🔑", f"ap:se:{i}")])
    return text, kb(*btns, pager("ap:s", page, pages_of(len(names))), [home_btn()])


def v_setting_ask(aid: int, idx: int) -> Screen:
    name = setting_names()[idx]
    kind = config.EDITABLE[name]
    hint = {int: "целое число", float: "число, можно с точкой", list: "через запятую, «-» — пусто",
            str: "текст, «-» — пусто"}.get(kind, "значение")
    back = f"ap:s:{CTX.get(aid, {}).get('sp', '0')}"
    return ask(aid, "set", back, "\n".join([
        head("🔑", h(name)), h(SETTING_INFO.get(name, "")), SEP,
        f"Сейчас: <code>{h(setting_value(name))}</code>",
        f"Пришлите новое значение ({hint}).",
    ]), name=name)


# ── Промо ─────────────────────────────────────────────────────────────

async def v_promo(aid: int) -> Screen:
    n = await db.one("SELECT COUNT(*) n, COALESCE(SUM(kop*uses_left),0) s FROM promocodes WHERE uses_left>0")
    k = await db.one("SELECT COUNT(*) n FROM promos")
    text = "\n".join([head("🏷", "Промо"), SEP,
                      line("🪙", f"Промокодов активно: <b>{n['n']}</b> · ещё могут выдать до <b>{rub(n['s'])}</b>"),
                      line("🌐", f"Скидок по странам: <b>{k['n']}</b>"),
                      "Скидка режет только наценку: цена не опустится ниже закупки + 1 ₽."])
    return text, kb([bt("Промокоды", "🪙", "ap:pc:0"), bt("Скидки по странам", "🌐", "ap:pk:0")], [home_btn()])


async def v_codes(aid: int, page: int, note: str = "") -> Screen:
    total = (await db.one("SELECT COUNT(*) n FROM promocodes"))["n"]
    page = clamp(page, total)
    CTX.setdefault(aid, {})["pc"] = str(page)
    rows = await db.all_("SELECT rowid rid, p.*, (SELECT COUNT(*) FROM promo_uses u WHERE u.code=p.code) used "
                         "FROM promocodes p ORDER BY created_at DESC LIMIT ? OFFSET ?", (PER, page * PER))
    lines = [f"<code>{h(r['code'])}</code> · {rub(r['kop'])} · осталось {r['uses_left']} · активировали {r['used']}"
             for r in rows]
    text = "\n".join(x for x in [note, head("🪙", "Промокоды"), f"Всего: <b>{total}</b>", SEP] + (lines or ["Пусто."])
                     + ["Нажмите на код, чтобы удалить."] if x)
    btns = [[bt(f"{short(r['code'], 16)} · {rub(r['kop'])} · {r['uses_left']}", "🏷", f"ap:pd:{r['rid']}")]
            for r in rows]
    return text, kb([bt("Создать", "➕", "ap:pn", "primary")], *btns,
                    pager("ap:pc", page, pages_of(total)), back_row("ap:p"))


async def v_code_del(aid: int, rid: int) -> Screen:
    r = await db.one("SELECT rowid rid, * FROM promocodes WHERE rowid=?", (rid,))
    back = f"ap:pc:{CTX.get(aid, {}).get('pc', '0')}"
    if r is None:
        return await v_codes(aid, 0, err_note("Такого кода уже нет"))
    text = "\n".join([head("🏷", "Удалить промокод?"), SEP,
                      kv([("Код", r["code"]), ("Сумма", rub(r["kop"])), ("Осталось", str(r["uses_left"]))]),
                      "Уже начисленные деньги останутся у людей."])
    return text, kb([bt("Удалить", "🛡", f"ap:pdy:{rid}", "danger"), bt("Назад", "⬅️", back)])


async def v_country_promos(aid: int, page: int, note: str = "") -> Screen:
    rows_all = sorted((await db.promos()).items())
    page = clamp(page, len(rows_all))
    chunk = rows_all[page * PER:(page + 1) * PER]
    lines = [f"<code>{h(c3)}</code> {h(countries.name_ru(c3))} · −{p} %" for c3, p in chunk]
    text = "\n".join(x for x in [note, head("🌐", "Скидки по странам"), f"Всего: <b>{len(rows_all)}</b>", SEP]
                     + (lines or ["Скидок нет."]) + ["Нажмите на страну, чтобы снять скидку."] if x)
    btns = [[bt(f"{c3} {countries.name_ru(c3)} · −{p} % · снять", "🌐", f"ap:pkd:{c3}")] for c3, p in chunk
            if re.fullmatch(r"[A-Z]{3}", c3)]
    return text, kb([bt("Задать скидку", "➕", "ap:pkn", "primary")], *btns,
                    pager("ap:pk", page, pages_of(len(rows_all))), back_row("ap:p"))


# ── Инструменты ───────────────────────────────────────────────────────

def v_tools(aid: int, note: str = "") -> Screen:
    text = "\n".join(x for x in [note, head("🚀", "Инструменты"), SEP,
                                 line("🎁", "Конкурс: провести розыгрыш дня сейчас"),
                                 line("📦", "Резерв: докупить до RESERVE_SIZE сейчас"),
                                 line("✨", "Набор премиум-эмодзи: создать или пересоздать"),
                                 line("💎", "Баланс LZT"),
                                 line("📋", "Выгрузка людей в CSV")] if x)
    return text, kb([bt("Конкурс сейчас", "🎁", "ap:tg"), bt("Докупить резерв", "📦", "ap:tr")],
                    [bt("Эмодзи-набор", "✨", "ap:te"), bt("Пересоздать набор", "↩️", "ap:ter")],
                    [bt("Баланс LZT", "💎", "ap:tl"), bt("Выгрузка CSV", "📋", "ap:tc")],
                    [home_btn()])


def confirm(title: str, body: str, yes: str, no: str = "ap:t") -> Screen:
    return "\n".join([head("🔔", title), SEP, body]), kb([bt("Да", "✅", yes, "primary"), bt("Нет", "⬅️", no)])


async def users_csv() -> bytes:
    rows = await db.all_("SELECT u.id, u.username, u.name, u.kop, u.created_at, u.banned, "
                         "COALESCE((SELECT SUM(price_kop) FROM orders o WHERE o.user_id=u.id AND o.status='done' "
                         "AND o.source IN ('live','reserve')),0) spent FROM users u ORDER BY u.id")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "username", "name", "balance_rub", "spent_rub", "created", "banned"])
    for r in rows:
        w.writerow([r["id"], r["username"], r["name"], f"{int(r['kop']) / 100:.2f}", f"{int(r['spent']) / 100:.2f}",
                    ts(r["created_at"]), r["banned"]])
    return buf.getvalue().encode("utf-8-sig")


# ── Маршруты callback ─────────────────────────────────────────────────

Handler = Callable[[CallbackQuery, int, list[str]], Awaitable[Screen | None]]
ROUTES: dict[str, Handler] = {}


def route(name: str):
    def deco(fn: Handler) -> Handler:
        ROUTES[name] = fn
        return fn
    return deco


def arg(p: list[str], i: int, lo: int = 0, hi: int = 10 ** 15) -> int | None:
    return to_int(p[i], lo, hi) if len(p) > i else None


@route("home")
async def r_home(c, aid, p):
    WAIT.pop(aid, None)
    return await v_home(aid)


@route("noop")
async def r_noop(c, aid, p):
    return None


@route("cancel")
async def r_cancel(c, aid, p):
    w = WAIT.pop(aid, None)
    back = (w or {}).get("back") or "ap:home"
    await say(c, "Отменено")
    return await dispatch(c, aid, back, nested=True)


# люди
@route("u")
async def r_users(c, aid, p):
    flt = p[2] if len(p) > 2 and p[2] in USER_FILTERS else "all"
    return await v_users(aid, flt, arg(p, 3, 0, 10 ** 6) or 0)


@route("us")
async def r_usearch(c, aid, p):
    return ask(aid, "usearch", CTX.get(aid, {}).get("ul", "ap:u:all:0"), "\n".join([
        head("🔎", "Поиск человека"), SEP,
        "Пришлите одно из:",
        "• <code>@username</code> или часть имени",
        "• ID, например <code>123456789</code>",
        "• номер телефона, например <code>+79991234567</code>",
        "• номер заказа, например <code>#123</code>",
    ]))


def _uid(p: list[str]) -> int | None:
    return arg(p, 2, 1, 10 ** 13)


@route("uc")
async def r_ucard(c, aid, p):
    uid = _uid(p)
    return await v_user(aid, uid) if uid else None


@route("uh")
async def r_uh(c, aid, p):
    uid = _uid(p)
    return await v_ledger(aid, uid, arg(p, 3, 0, 10 ** 6) or 0) if uid else None


@route("ui")
async def r_ui(c, aid, p):
    uid = _uid(p)
    return await v_invoices(aid, uid, arg(p, 3, 0, 10 ** 6) or 0) if uid else None


@route("uo")
async def r_uo(c, aid, p):
    uid = _uid(p)
    return await v_user_orders(aid, uid, arg(p, 3, 0, 10 ** 6) or 0) if uid else None


@route("ur")
async def r_ur(c, aid, p):
    uid = _uid(p)
    return await v_refs(aid, uid, arg(p, 3, 0, 10 ** 6) or 0) if uid else None


async def _need_user(c, uid) -> Any:
    u = await db.get_user(uid) if uid else None
    if u is None:
        await say(c, "Нет такого человека", show_alert=True)
    return u


@route("ub")
async def r_ubal(c, aid, p):
    u = await _need_user(c, _uid(p))
    if u is None:
        return None
    return ask(aid, "ubal", f"ap:uc:{u['id']}", "\n".join([
        head("🪙", "Начислить или списать"), f"{who(u)} · <code>{u['id']}</code>", SEP,
        f"Баланс: <b>{rub(u['kop'])}</b>",
        "Пришлите сумму в рублях: <code>100</code> — начислить, <code>-50</code> — списать.",
        "В истории запишется как «админ».",
    ]), uid=int(u["id"]))


@route("ux")
async def r_uban(c, aid, p):
    u = await _need_user(c, _uid(p))
    if u is None:
        return None
    return ask(aid, "uban", f"ap:uc:{u['id']}", "\n".join([
        head("🛡", "Бан"), f"{who(u)} · <code>{u['id']}</code>", SEP,
        "Пришлите причину сообщением — её увидят в карточке.",
        "Бан закрывает покупки, переводы и конкурсы.",
    ]), extra=[[bt("Без причины", "🛡", f"ap:uxn:{u['id']}", "danger")]], uid=int(u["id"]))


@route("uxn")
async def r_uban_now(c, aid, p):
    u = await _need_user(c, _uid(p))
    if u is None:
        return None
    WAIT.pop(aid, None)
    await db.set_ban(int(u["id"]), "нарушение условий")
    await say(c, "Забанен")
    return await v_user(aid, int(u["id"]))


@route("uxu")
async def r_unban(c, aid, p):
    u = await _need_user(c, _uid(p))
    if u is None:
        return None
    await db.set_ban(int(u["id"]), "")
    await say(c, "Разбанен")
    return await v_user(aid, int(u["id"]))


@route("ut")
async def r_trusted(c, aid, p):
    u = await _need_user(c, _uid(p))
    if u is None:
        return None
    if not await has_trusted():
        await say(c, "В базе ещё нет колонки trusted", show_alert=True)
        return None
    await db.run("UPDATE users SET trusted=CASE WHEN trusted=1 THEN 0 ELSE 1 END WHERE id=?", (u["id"],))
    nu = await db.get_user(int(u["id"]))
    await say(c, "Доверенный: без лимита" if nu["trusted"] else "Обычный лимит покупок")
    return await v_user(aid, int(u["id"]))


@route("um")
async def r_umsg(c, aid, p):
    u = await _need_user(c, _uid(p))
    if u is None:
        return None
    return ask(aid, "umsg", f"ap:uc:{u['id']}", "\n".join([
        head("💬", "Написать"), f"{who(u)} · <code>{u['id']}</code>", SEP,
        "Пришлите сообщение — бот перешлёт его копией от своего имени (оформление и медиа сохранятся).",
    ]), uid=int(u["id"]))


# заказы
@route("o")
async def r_orders(c, aid, p):
    flt = p[2] if len(p) > 2 and p[2] in ORDER_FILTERS else "all"
    return await v_orders(aid, flt, arg(p, 3, 0, 10 ** 6) or 0)


@route("oc")
async def r_order(c, aid, p):
    oid = arg(p, 2, 1, 10 ** 12)
    return await v_order(aid, oid) if oid else None


@route("os")
async def r_osearch(c, aid, p):
    return ask(aid, "osearch", CTX.get(aid, {}).get("ol", "ap:o:all:0"), "\n".join([
        head("🔎", "Поиск заказа"), SEP,
        "Пришлите номер телефона (<code>+79991234567</code>) или номер заказа (<code>#123</code>).",
    ]))


# рассылка
@route("b")
async def r_bc(c, aid, p):
    return await v_bc(aid)


@route("bd")
async def r_bc_draft(c, aid, p):
    return await v_bc_draft(aid)


@route("bb")
async def r_bc_buttons(c, aid, p):
    if aid not in DRAFT:
        return await v_bc(aid)
    return ask(aid, "bcbtn", "ap:bd", "\n".join([
        head("➕", "Кнопки рассылки"), SEP,
        "Одна строка — один ряд. Формат:",
        "<code>Текст кнопки | https://ссылка</code>",
        "Несколько в ряд — через <code> ;; </code>",
        "Цвет — в конце: <code>#blue</code>, <code>#green</code>, <code>#red</code>",
        "Премиум-эмодзи в начале строки станет иконкой кнопки.",
        "Пришлите <code>-</code>, чтобы убрать кнопки.",
    ]))


@route("bv")
async def r_bc_view(c, aid, p):
    if aid not in DRAFT:
        return await v_bc(aid)
    note = await bc_preview(c.bot, aid)
    await say(c, )
    scr = await v_bc_draft(aid, note)
    sent = await _send(c.bot, aid, *scr)
    if sent is not None:
        PANEL[aid] = (sent.chat.id, sent.message_id)
    return None


@route("bs")
async def r_bc_send(c, aid, p):
    t = p[2] if len(p) > 2 and p[2] in BC_TARGETS else None
    if not t or aid not in DRAFT:
        return await v_bc(aid)
    if bc_running():
        await say(c, "Рассылка уже идёт", show_alert=True)
        return await v_bc(aid)
    n = await bc_count(t)
    return confirm("Запустить рассылку?", f"Получат: <b>{n}</b> чел. ({BC_TARGETS[t][0].lower()}).\n"
                   "Остановить можно в любой момент.", f"ap:bsy:{t}", "ap:bd")


@route("bsy")
async def r_bc_go(c, aid, p):
    t = p[2] if len(p) > 2 and p[2] in BC_TARGETS else None
    if not t:
        return None
    return await bc_start(c, t)


@route("bp")
async def r_bc_progress(c, aid, p):
    if not BC:
        return await v_bc(aid)
    if bc_running():
        return await v_bc(aid)
    return bc_progress_text(), kb([home_btn()])


@route("bstop")
async def r_bc_stop(c, aid, p):
    if bc_running():
        BC["stop"] = True
        await say(c, "Останавливаю")
    if bc_running():
        return await v_bc(aid)
    return bc_progress_text(), kb([home_btn()])


@route("bx")
async def r_bc_cancel(c, aid, p):
    DRAFT.pop(aid, None)
    WAIT.pop(aid, None)
    await say(c, "Черновик удалён")
    return await v_home(aid)


# главное меню
@route("m")
async def r_menu(c, aid, p):
    return await v_menu(aid)


@route("mm")
async def r_menu_media(c, aid, p):
    return ask(aid, "mmedia", "ap:m", "\n".join([
        head("📱", "Медиа главного меню"), SEP,
        "Пришлите фото, GIF или видео. Если у него есть подпись — она станет текстом меню.",
    ]))


@route("mt")
async def r_menu_text(c, aid, p):
    return ask(aid, "mtext", "ap:m", "\n".join([
        head("📋", "Текст главного меню"), SEP,
        "Пришлите текст с оформлением: жирный, курсив, ссылки, спойлеры и премиум-эмодзи сохранятся.",
        "С медиа подпись — не больше 1024 символов.",
    ]))


@route("mp")
async def r_menu_preview(c, aid, p):
    await say(c, )
    note = await menu_preview(c.bot, aid, c.from_user.first_name or "")
    scr = await v_menu(aid, note)
    sent = await _send(c.bot, aid, *scr)
    if sent is not None:
        PANEL[aid] = (sent.chat.id, sent.message_id)
    return None


@route("ms")
async def r_menu_style(c, aid, p):
    s = p[2] if len(p) > 2 else ""
    s = "" if s == "plain" else s
    if s not in dict(STYLES):
        return None
    await db.set_setting("menu_button_style", s)
    await say(c, f"Кнопка: {dict(STYLES)[s]}")
    return await v_menu(aid)


@route("mn")
async def r_menu_nomedia(c, aid, p):
    await db.set_setting("menu_media_kind", "none")
    await db.set_setting("menu_media_id", "")
    await say(c, "Меню без медиа")
    return await v_menu(aid)


@route("mr")
async def r_menu_reset(c, aid, p):
    what = p[2] if len(p) > 2 else ""
    if what not in ("media", "text", "all"):
        return None
    if what in ("media", "all"):
        await db.set_setting("menu_media_kind", "")
        await db.set_setting("menu_media_id", "")
    if what in ("text", "all"):
        await db.set_setting("menu_text", "")
    if what == "all":
        await db.set_setting("menu_button_style", "")
    await say(c, "Сброшено")
    return await v_menu(aid)


# настройки
@route("s")
async def r_settings(c, aid, p):
    WAIT.pop(aid, None)
    return await v_settings(aid, arg(p, 2, 0, 1000) or 0)


@route("se")
async def r_setting(c, aid, p):
    idx = arg(p, 2, 0, len(setting_names()) - 1)
    if idx is None:
        return None
    name = setting_names()[idx]
    if config.EDITABLE[name] is bool:
        new = "0" if getattr(config, name, False) else "1"
        ok = await db.set_override(name, new)
        await say(c, f"{name}: {'вкл' if new == '1' else 'выкл'}" if ok else "Не удалось", show_alert=not ok)
        return await v_settings(aid, idx // PER)
    return v_setting_ask(aid, idx)


# промо
@route("p")
async def r_promo(c, aid, p):
    return await v_promo(aid)


@route("pc")
async def r_codes(c, aid, p):
    return await v_codes(aid, arg(p, 2, 0, 10 ** 6) or 0)


@route("pn")
async def r_code_new(c, aid, p):
    return ask(aid, "pnew", f"ap:pc:{CTX.get(aid, {}).get('pc', '0')}", "\n".join([
        head("➕", "Новый промокод"), SEP,
        "Пришлите: <code>КОД сумма активаций</code>",
        "Например <code>SALE 50 100</code> — 50 ₽ × 100 активаций.",
        "Код: латиница, цифры, _ и -, до 32 символов. Тот же код — обновится.",
    ]))


@route("pd")
async def r_code_del(c, aid, p):
    rid = arg(p, 2, 1, 10 ** 12)
    return await v_code_del(aid, rid) if rid else None


@route("pdy")
async def r_code_del_yes(c, aid, p):
    rid = arg(p, 2, 1, 10 ** 12)
    if not rid:
        return None
    r = await db.one("SELECT code FROM promocodes WHERE rowid=?", (rid,))
    if r:
        await db.run("DELETE FROM promocodes WHERE rowid=?", (rid,))
        await say(c, "Удалён")
    return await v_codes(aid, int(CTX.get(aid, {}).get("pc", "0") or 0))


@route("pk")
async def r_cpromos(c, aid, p):
    return await v_country_promos(aid, arg(p, 2, 0, 10 ** 6) or 0)


@route("pkn")
async def r_cpromo_new(c, aid, p):
    return ask(aid, "pknew", "ap:pk:0", "\n".join([
        head("🌐", "Скидка на страну"), SEP,
        "Пришлите: <code>RUS 5</code> — страна ISO-3 и скидка 1–50 %.",
        "<code>RUS 0</code> — снять. Цена не опустится ниже закупки + 1 ₽.",
    ]))


@route("pkd")
async def r_cpromo_del(c, aid, p):
    c3 = p[2] if len(p) > 2 and re.fullmatch(r"[A-Z]{3}", p[2]) else None
    if not c3:
        return None
    await db.set_promo(c3, 0)
    await say(c, f"Скидка {c3} снята")
    return await v_country_promos(aid, 0)


# инструменты
@route("t")
async def r_tools(c, aid, p):
    return v_tools(aid)


@route("tg")
async def r_tool_gw(c, aid, p):
    st = await shop.giveaway_state()
    return confirm("Провести конкурс сейчас?",
                   f"Участников сегодня: <b>{st['count']}</b>. Проверка маржи за сутки будет пропущена.", "ap:tgy")


@route("tgy")
async def r_tool_gw_yes(c, aid, p):
    await say(c, "Разыгрываю…")
    try:
        res = await shop.draw(force=True)
    except Exception as exc:  # noqa: BLE001
        return v_tools(aid, err_note(f"Ошибка конкурса: {h(exc)}"))
    st = res.get("status")
    if st == "done":
        u = await db.get_user(int(res["winner"]))
        note = ok_note(f"Победитель: {who(u)} · заказ #{res.get('order')} · участников {res.get('entries')}")
    else:
        note = err_note(f"Конкурс: {h(st)} · {h(res.get('note', ''))}")
    return v_tools(aid, note)


@route("tr")
async def r_tool_reserve(c, aid, p):
    await say(c, "Докупаю резерв…")
    try:
        await shop.keep_reserve()
    except Exception as exc:  # noqa: BLE001
        return v_tools(aid, err_note(f"Резерв: {h(exc)}"))
    r = await db.one("SELECT COUNT(*) n, COALESCE(SUM(cost_kop),0) c FROM reserve WHERE status='ready'")
    return v_tools(aid, ok_note(f"Резерв: {r['n']} шт на {rub(r['c'])} (цель {config.RESERVE_SIZE})"))


async def _emoji(c, aid, recreate: bool) -> Screen:
    await say(c, "Создаю набор…" if recreate else "Проверяю набор…")
    try:
        ok, text = await emoji.create(c.bot, aid, recreate=recreate)
    except Exception as exc:  # noqa: BLE001
        ok, text = False, str(exc)
    return v_tools(aid, (ok_note if ok else err_note)(h(text)))


@route("te")
async def r_tool_emoji(c, aid, p):
    return await _emoji(c, aid, False)


@route("ter")
async def r_tool_emoji_re(c, aid, p):
    return confirm("Пересоздать набор эмодзи?", "Старый набор удалится, ID всех премиум-эмодзи поменяются. "
                   "Нужен Telegram Premium у владельца.", "ap:tery")


@route("tery")
async def r_tool_emoji_re_yes(c, aid, p):
    return await _emoji(c, aid, True)


@route("tl")
async def r_tool_lzt(c, aid, p):
    bal = await lzt_balance(fresh=True)
    note = err_note("LZT не ответил") if bal is None else ok_note(f"Баланс LZT: {rub(int(round(bal * 100)))}")
    return v_tools(aid, note + (" · демо" if config.LZT_DEMO else ""))


@route("tc")
async def r_tool_csv(c, aid, p):
    data = await users_csv()
    name = f"users_{dt.datetime.now(MSK):%Y%m%d_%H%M}.csv"
    n_rows = max(0, data.count(b"\n") - 1)
    await say(c, "Готовлю файл…")
    try:
        await c.bot.send_document(aid, BufferedInputFile(data, filename=name), caption=f"Люди: {n_rows} строк")
    except TelegramAPIError as exc:
        return v_tools(aid, err_note(f"Файл не отправился: {h(exc)}"))
    scr = v_tools(aid, ok_note("Выгрузка отправлена"))
    sent = await _send(c.bot, aid, *scr)
    if sent is not None:
        PANEL[aid] = (sent.chat.id, sent.message_id)
    return None


async def dispatch(c: CallbackQuery, aid: int, data: str, nested: bool = False) -> Screen | None:
    if not data.startswith("ap:") or len(data.encode()) > 64:
        return None
    p = data.split(":")
    fn = ROUTES.get(p[1]) if len(p) > 1 else None
    if fn is None or (nested and p[1] == "cancel"):
        return None
    return await fn(c, aid, p)


class IsAdmin(Filter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        u = getattr(event, "from_user", None)
        return bool(u and is_admin(u.id))


@router.callback_query(F.data.startswith("ap:"), IsAdmin())
async def on_callback(c: CallbackQuery) -> None:
    aid = c.from_user.id
    if not is_admin(aid):        # повторная проверка: данные callback можно подделать
        return
    try:
        scr = await dispatch(c, aid, c.data or "")
    except Exception:
        log.exception("админка %s", c.data)
        await _safe_answer(c, "Ошибка — подробности в логе", True)
        return
    if scr is not None:
        await show(c, scr)
    await _safe_answer(c)


async def _safe_answer(c: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    if c.id not in _ANSWERED:
        await say(c, text, show_alert=alert)
    _ANSWERED.discard(c.id)


async def say(c: CallbackQuery | None, text: str | None = None, show_alert: bool = False) -> None:
    """Ответ на callback один раз (повторный Telegram всё равно отклонит)."""
    if c is None or c.id in _ANSWERED:
        return
    _ANSWERED.add(c.id)
    try:
        await c.answer(text, show_alert=show_alert)
    except TelegramAPIError:
        pass


# ── Команда и ввод ────────────────────────────────────────────────────

@router.message(Command("admin"), F.chat.type == "private", IsAdmin())
async def cmd_admin(m: Message) -> None:
    WAIT.pop(m.from_user.id, None)
    text, markup = await v_home(m.from_user.id)
    sent = await _send(m.bot, m.chat.id, text, markup)
    if sent is not None:
        PANEL[m.from_user.id] = (sent.chat.id, sent.message_id)


class Pending(Filter):
    """Срабатывает только когда этот админ сейчас что-то вводит."""

    async def __call__(self, m: Message) -> bool:
        u = m.from_user
        if not u or not is_admin(u.id) or m.chat.type != "private":
            return False
        w = WAIT.get(u.id)
        if not w:
            return False
        if time.time() - w["ts"] > WAIT_TTL:
            WAIT.pop(u.id, None)
            return False
        return not (m.text or "").startswith("/")


@router.message(Pending())
async def on_input(m: Message) -> None:
    aid = m.from_user.id
    w = WAIT.get(aid)
    if not w or not is_admin(aid):
        return
    kind = w["kind"]
    text = (m.text or "").strip()
    try:
        await INPUTS[kind](m, aid, w, text)
    except Exception:
        log.exception("ввод админки %s", kind)
        await m.answer("Ошибка — подробности в логе")


async def in_usearch(m, aid, w, text):
    if not text:
        return await m.answer("Нужен текст: @ник, ID, номер или #заказ")
    rows, how = await search_users(text[:64])
    if not rows:
        return await reply(m, await r_usearch(None, aid, []), err_note(f"Никого не нашёл: {h(short(text, 40))}"))
    WAIT.pop(aid, None)
    if len(rows) == 1:
        return await reply(m, await v_user(aid, int(rows[0]["id"])), line("🔎", f"Найден {how}"))
    await reply(m, v_found(rows, how, "ap:us"))


async def in_ubal(m, aid, w, text):
    uid = int(w["uid"])
    try:
        val = float(text.replace(" ", "").replace(",", ".").replace("₽", ""))
    except ValueError:
        return await m.answer("Нужна сумма, например 100 или -50")
    kop = int(round(val * 100))
    if kop == 0 or abs(kop) > 10_000_000_00:
        return await m.answer("Сумма должна быть не нулём и не больше 10 000 000 ₽")
    if not await db.get_user(uid):
        WAIT.pop(aid, None)
        return await m.answer("Нет такого человека")
    WAIT.pop(aid, None)
    left = await db.add_kop(uid, kop, "admin", f"by {aid}")
    sign = "+" if kop > 0 else ""
    await reply(m, await v_user(aid, uid), ok_note(f"{sign}{rub(kop)} · баланс {rub(left)}"))


async def in_uban(m, aid, w, text):
    uid = int(w["uid"])
    if not text:
        return await m.answer("Нужна причина текстом")
    WAIT.pop(aid, None)
    await db.set_ban(uid, text[:200])
    await reply(m, await v_user(aid, uid), ok_note("Забанен"))


async def in_umsg(m, aid, w, text):
    uid = int(w["uid"])
    WAIT.pop(aid, None)
    try:
        await m.bot.copy_message(uid, m.chat.id, m.message_id)
        note = ok_note("Сообщение доставлено")
    except TelegramForbiddenError:
        await db.run("UPDATE users SET blocked=1 WHERE id=?", (uid,))
        note = err_note("Человек заблокировал бота")
    except TelegramAPIError as exc:
        note = err_note(f"Не доставлено: {h(exc)}")
    await reply(m, await v_user(aid, uid), note)


async def in_osearch(m, aid, w, text):
    q = text.replace(" ", "")
    if q.startswith("#") or (q.isdigit() and len(q) <= 7):
        oid = to_int(q.lstrip("#"), 1, 10 ** 12)
        o = await db.get_order(oid) if oid else None
        if o is None:
            return await m.answer("Такого заказа нет")
        WAIT.pop(aid, None)
        return await reply(m, await v_order(aid, oid))
    rows = await db.whois(q)
    if not rows:
        return await m.answer("Такой номер мы не выдавали")
    WAIT.pop(aid, None)
    if len(rows) == 1:
        return await reply(m, await v_order(aid, int(rows[0]["id"])))
    text_ = "\n".join([head("🔎", "Заказы по номеру"), f"<code>{h(q)}</code> · найдено {len(rows)}", SEP]
                      + [f"<code>#{r['id']}</code> {who(r) if r['name'] or r['username'] else ''} · "
                         f"<code>{r['user_id']}</code> · {ts(r['created_at'])}" + (" · бан" if r["banned"] else "")
                         for r in rows])
    await reply(m, (text_, kb(*[order_btn(r) for r in rows], [home_btn()])))


async def in_bc(m, aid, w, text):
    if m.media_group_id:
        key = (aid, str(m.media_group_id))
        _ALBUM.setdefault(key, []).append(m.message_id)
        if key not in _ALBUM_TASK:
            _ALBUM_TASK[key] = asyncio.create_task(_album_done(m.bot, aid, m.chat.id, key))
        return
    WAIT.pop(aid, None)
    DRAFT[aid] = {"chat": m.chat.id, "ids": [m.message_id], "album": False, "kb": None, "what": msg_kind(m)}
    note = await bc_preview(m.bot, aid)
    await reply(m, await v_bc_draft(aid, note))


async def in_bcbtn(m, aid, w, text):
    d = DRAFT.get(aid)
    if not d:
        WAIT.pop(aid, None)
        return await reply(m, await v_bc(aid))
    if not m.text:
        return await m.answer("Нужен текст со строками кнопок")
    if text in ("-", "нет", "—"):
        d["kb"] = None
        WAIT.pop(aid, None)
        note = await bc_preview(m.bot, aid)
        return await reply(m, await v_bc_draft(aid, note or ok_note("Кнопки убраны")))
    rows, errs = parse_buttons(m.text, m.entities)
    if errs or not rows:
        return await m.answer("Не понял кнопки:\n" + "\n".join(h(e) for e in (errs or ["пусто"])) +
                              "\n\nФормат: <code>Текст | https://ссылка #blue</code>", parse_mode="HTML")
    d["kb"] = InlineKeyboardMarkup(inline_keyboard=rows)
    WAIT.pop(aid, None)
    note = await bc_preview(m.bot, aid)
    await reply(m, await v_bc_draft(aid, note))


async def in_mmedia(m, aid, w, text):
    if m.photo:
        fid, kind = m.photo[-1].file_id, "photo"
    elif m.animation:
        fid, kind = m.animation.file_id, "animation"
    elif m.video:
        fid, kind = m.video.file_id, "video"
    else:
        return await m.answer("Нужно фото, GIF или видео")
    WAIT.pop(aid, None)
    await db.set_setting("menu_media_id", fid)
    await db.set_setting("menu_media_kind", kind)
    note = ok_note(f"Медиа меню: {MEDIA_NAME[kind]}")
    if m.caption:
        await db.set_setting("menu_text", m.html_text)
        note += "\n" + ok_note("Подпись стала текстом меню")
    prev = await menu_preview(m.bot, aid, m.from_user.first_name or "")
    await reply(m, await v_menu(aid, "\n".join(x for x in (note, prev) if x)))


async def in_mtext(m, aid, w, text):
    if not m.text:
        return await m.answer("Нужен текст сообщением")
    WAIT.pop(aid, None)
    await db.set_setting("menu_text", m.html_text)
    prev = await menu_preview(m.bot, aid, m.from_user.first_name or "")
    await reply(m, await v_menu(aid, "\n".join(x for x in (ok_note("Текст меню сохранён"), prev) if x)))


async def in_set(m, aid, w, text):
    name = w["name"]
    if name not in config.EDITABLE or not text:
        return await m.answer("Нужно значение текстом")
    kind = config.EDITABLE[name]
    raw = "" if text in ("-", "—") and kind in (str, list) else text[:300]
    if kind in (int, float):
        try:
            num = float(raw.replace(",", "."))
            if num < 0 or (kind is int and num != int(num)):
                raise ValueError
            if name == "GIVEAWAY_HOUR" and not 0 <= num <= 23:
                raise ValueError
        except ValueError:
            return await m.answer("Не подходит: нужно " + ("целое неотрицательное число" if kind is int
                                                           else "неотрицательное число"))
        raw = str(int(num)) if kind is int else raw.replace(",", ".")
    if not await db.set_override(name, raw):
        return await m.answer("Не подошло, попробуйте ещё раз")
    WAIT.pop(aid, None)
    page = setting_names().index(name) // PER
    await reply(m, await v_settings(aid, page, ok_note(f"{h(name)} = {h(setting_value(name))}")))


async def in_pnew(m, aid, w, text):
    parts = text.split()
    try:
        code, rub_, uses = parts[0].upper(), float(parts[1].replace(",", ".")), int(parts[2])
        if len(parts) != 3 or not re.fullmatch(r"[A-Z0-9_-]{2,32}", code):
            raise ValueError
        if not (0 < rub_ <= 100_000) or not (1 <= uses <= 1_000_000):
            raise ValueError
    except (IndexError, ValueError):
        return await m.answer("Формат: КОД сумма активаций, например SALE 50 100")
    WAIT.pop(aid, None)
    kop = int(round(rub_ * 100))
    await db.create_promo(code, kop, uses)
    await reply(m, await v_codes(aid, 0, ok_note(f"Промокод {h(code)}: {rub(kop)} × {uses} = до {rub(kop * uses)}")))


async def in_pknew(m, aid, w, text):
    parts = text.upper().split()
    if len(parts) != 2 or not re.fullmatch(r"[A-Z]{3}", parts[0]) or not parts[1].isdigit() \
            or int(parts[1]) > 50:
        return await m.answer("Формат: RUS 5 (скидка 0–50 %)")
    WAIT.pop(aid, None)
    await db.set_promo(parts[0], int(parts[1]))
    note = ok_note(f"{parts[0]}: −{parts[1]} %") if int(parts[1]) else ok_note(f"Скидка {parts[0]} снята")
    await reply(m, await v_country_promos(aid, 0, note))


INPUTS: dict[str, Callable[..., Awaitable[Any]]] = {
    "usearch": in_usearch, "ubal": in_ubal, "uban": in_uban, "umsg": in_umsg, "osearch": in_osearch,
    "bc": in_bc, "bcbtn": in_bcbtn, "mmedia": in_mmedia, "mtext": in_mtext, "set": in_set,
    "pnew": in_pnew, "pknew": in_pknew,
}
