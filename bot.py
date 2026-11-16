"""Бот: главное меню с баннером, язык, обучение, конкурс, звёзды, админка.

Всё, что связано с покупкой, живёт в Mini App. Бот — это вход,
уведомления и админ-команды.

Премиум-эмодзи: и в тексте (<tg-emoji>), и на кнопках
(icon_custom_emoji_id) — из своего набора, который бот создаёт сам
(/emoji). Если Telegram отбил кнопки с иконками (у владельца бота нет
Premium), меню уходит без иконок, а через 10 минут бот пробует снова.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup,
    Message, PreCheckoutQuery, WebAppInfo,
)

import config
import db
import emoji
import i18n
import shop

log = logging.getLogger("numbers.bot")
router = Router(name="main")
BANNER = config.BASE_DIR / "assets" / "banner.jpg"

_icons_off_at = 0.0


def _icons_on() -> bool:
    return time.time() - _icons_off_at > 600


def _e(ch: str) -> str:
    """Премиум-эмодзи для текста. Нет премиума — пусто: обычные эмодзи не выводим."""
    return emoji.tag(ch)


def _btn(text: str, ch: str, **kw) -> InlineKeyboardButton:
    icon = emoji.get(ch) if _icons_on() else None
    if icon:
        return InlineKeyboardButton(text=text, icon_custom_emoji_id=icon, **kw)
    # Без премиум-иконки — только текст: обычный эмодзи на кнопку не ставим.
    return InlineKeyboardButton(text=text, **kw)


JOIN_OK = {"en": "You're in!", "ru": "Вы участвуете!", "es": "¡Estás dentro!", "ar": "أنت مشارك!",
           "hi": "आप शामिल हैं!", "zh": "已参加！"}
JOIN = {"en": "Join", "ru": "Участвовать", "es": "Participar", "ar": "شارك", "hi": "भाग लें", "zh": "参加"}


def _webapp(path: str = "") -> WebAppInfo | None:
    return WebAppInfo(url=config.WEBAPP_URL + "/" + path.lstrip("/")) if config.webapp_enabled() else None


def _support_url() -> str:
    s = config.SUPPORT.strip()
    if not s:
        return ""
    return s if s.startswith("http") else f"https://t.me/{s.lstrip('@')}"


#: Вид главного меню из админ-панели (settings: menu_media_id/kind, menu_text,
#: menu_button_style). Обновляется перед каждой отправкой меню.
MENU = {"media": "", "kind": "", "text": "", "style": ""}


async def load_menu() -> None:
    for key, name in (("media", "menu_media_id"), ("kind", "menu_media_kind"),
                      ("text", "menu_text"), ("style", "menu_button_style")):
        MENU[key] = await db.get_setting(name)


def menu_kb(lang: str) -> InlineKeyboardMarkup:
    t = lambda k: i18n.t(k, lang)  # noqa: E731
    rows = []
    wa = _webapp()
    import textmode as tm  # текстовая версия: тот же магазин кнопками в чате
    if wa:
        style = MENU["style"] if MENU["style"] in ("primary", "success", "danger") else None
        rows.append([_btn(t("open"), "📱", web_app=wa, style=style)])
    rows.append([_btn(tm.tt("catalog", lang), "🛒", callback_data="tm:cat:all:0"),
                 _btn(tm.tt("profile", lang), "👤", callback_data="tm:p")])
    rows.append([_btn(t("howto"), "📖", callback_data="howto"), _btn(t("gw"), "🎁", callback_data="gw")])
    last = [_btn(t("lang"), "🌐", callback_data="lang")]
    if _support_url():
        last.append(_btn(t("support"), "💬", url=_support_url()))
    rows.append(last)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_text(lang: str, name: str, kop: int) -> str:
    if MENU["text"]:
        # Свой текст из админки; {name} и {balance} подставляются, если есть.
        return MENU["text"].replace("{name}", html.escape(name or "")).replace("{balance}", shop.money(kop))
    return (f"{_e('👋')} <b>{html.escape(i18n.t('hi', lang, name=name or 'friend'))}</b>\n\n"
            f"{_e('📱')} {i18n.t('menu', lang)}\n\n"
            f"{_e('💳')} <b>{shop.money(kop)}</b>")


async def _send(bot: Bot, chat_id: int, text: str, kb_fn, lang: str, photo: bool = True) -> None:
    """Шлёт меню. Отбили иконки или премиум-эмодзи — повторяет без них."""
    global _icons_off_at
    await load_menu()
    for attempt in range(2):
        kb = kb_fn(lang)
        try:
            kind, media = MENU["kind"], MENU["media"]
            if photo and kind == "none":
                await bot.send_message(chat_id, text, reply_markup=kb)
            elif photo and media and kind in ("photo", "animation", "video"):
                send = {"photo": bot.send_photo, "animation": bot.send_animation, "video": bot.send_video}[kind]
                await send(chat_id, media, caption=text, reply_markup=kb)
            elif photo and BANNER.exists():
                fid = await db.get_setting("banner_file_id")
                msg = await bot.send_photo(chat_id, fid or FSInputFile(BANNER), caption=text, reply_markup=kb)
                if not fid and msg.photo:
                    await db.set_setting("banner_file_id", msg.photo[-1].file_id)
            else:
                await bot.send_message(chat_id, text, reply_markup=kb)
            return
        except TelegramAPIError as exc:
            low = str(exc).lower()
            if attempt == 0 and ("button" in low or "emoji" in low or "entit" in low):
                log.warning("меню с премиум-эмодзи не принято: %s — шлю без них", exc)
                _icons_off_at = time.time()
                text = _plain(text)
                continue
            if attempt == 0 and "file" in low:
                await db.set_setting("banner_file_id", "")
                continue
            raise


def _plain(text: str) -> str:
    """Убирает премиум-эмодзи целиком (если Telegram их не принял) — без замены на обычные."""
    import re
    text = re.sub(r'<tg-emoji emoji-id="\d+">.*?</tg-emoji>\s?', "", text)
    return re.sub(r"(?m)^ +", "", text)


# ── Пользователь ──────────────────────────────────────────────────────

@router.message(CommandStart())
async def start(m: Message, command: CommandObject) -> None:
    u = await db.touch_user(m.from_user.id, m.from_user.full_name, m.from_user.username or "")
    lang = u["lang"]
    if not lang:
        lang = i18n.pick(m.from_user.language_code)
        await db.set_lang(m.from_user.id, lang)
    args = command.args or ""
    if (args.startswith("ref") and args[3:].isdigit() and len(args) <= 18
            and await db.set_ref(m.from_user.id, int(args[3:]))):
        inviter = int(args[3:])
        st = await shop.ref_state(inviter)
        await notify(inviter, "ref_new", name=m.from_user.first_name or "—",
                     n=st["invited"], goal=st["goal"])
    import gate
    if (gate.active() and m.from_user.id not in config.ADMIN_IDS
            and not await shop.is_subscribed(m.from_user.id)):
        gate.PENDING[m.from_user.id] = args
        return await gate.send(m.bot, m.chat.id, lang)
    await _send(m.bot, m.chat.id, menu_text(lang, m.from_user.first_name, int(u["kop"])), menu_kb, lang)
    if args == "gw":
        await _gw_card(m.bot, m.chat.id, m.from_user.id, lang)


async def _lang_of(uid: int) -> str:
    u = await db.get_user(uid)
    return i18n.pick(u["lang"] if u else "en")


@router.callback_query(F.data == "nowebapp")
async def nowebapp(c: CallbackQuery) -> None:
    await c.answer("WEBAPP_URL не настроен", show_alert=True)


@router.callback_query(F.data == "howto")
async def howto(c: CallbackQuery) -> None:
    lang = await _lang_of(c.from_user.id)
    steps = i18n.t("tour", lang).split("\n")
    marks = ["💳", "🔎", "🛒", "🔑"]
    body = "\n\n".join(f"{_e(marks[i % 4])} {html.escape(s)}" for i, s in enumerate(steps))
    kb = InlineKeyboardMarkup(inline_keyboard=[[_btn(i18n.t("open", lang), "📱", web_app=_webapp("?tour=1"))]]
                              if config.webapp_enabled() else [])
    try:
        await c.message.answer(f"<b>{i18n.t('howto', lang)}</b>\n\n{body}", reply_markup=kb)
    except TelegramAPIError:
        await c.message.answer(_plain(f"<b>{i18n.t('howto', lang)}</b>\n\n{body}"))
    await c.answer()


@router.callback_query(F.data == "lang")
async def lang_menu(c: CallbackQuery) -> None:
    items = list(i18n.LANGS.items())
    rows = [[InlineKeyboardButton(text=name, callback_data=f"setlang:{code}") for code, name in items[i:i + 3]]
            for i in range(0, len(items), 3)]
    await c.message.answer(f"{_e('🌐')} Language / Язык", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


@router.callback_query(F.data.startswith("setlang:"))
async def set_lang(c: CallbackQuery) -> None:
    code = c.data.split(":", 1)[1]
    if code not in i18n.LANGS:
        return await c.answer()
    await db.set_lang(c.from_user.id, code)
    u = await db.get_user(c.from_user.id)
    try:
        await c.message.delete()
    except TelegramAPIError:
        pass
    await _send(c.bot, c.from_user.id, menu_text(code, c.from_user.first_name, int(u["kop"])), menu_kb, code)
    await c.answer(i18n.LANGS[code])


async def _gw_card(bot: Bot, chat_id: int, uid: int, lang: str) -> None:
    st = await shop.giveaway_state(uid)
    rows = []
    if config.CHANNEL_URL:
        rows.append([_btn(config.CHANNEL or "Channel", "📢", url=config.CHANNEL_URL)])
    if not st["joined"]:
        rows.append([_btn(JOIN.get(lang, JOIN["en"]), "🎁", callback_data="gw:join")])
    if config.webapp_enabled():
        rows.append([_btn(i18n.t("open", lang), "📱", web_app=_webapp("?tab=gw"))])
    left = max(0, st["draw_at"] - int(time.time()))
    text = (f"{_e('🎁')} <b>{i18n.t('gw', lang)}</b>\n\n{html.escape(i18n.t('gw_new', lang))}\n\n"
            f"{_e('👥')} {st['count']}   {_e('⏰')} {left // 3600:02d}:{left % 3600 // 60:02d}"
            + (f"\n{_e('✅')}" if st["joined"] else ""))
    try:
        await bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except TelegramAPIError:
        await bot.send_message(chat_id, _plain(text), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "gw")
async def gw(c: CallbackQuery) -> None:
    await _gw_card(c.bot, c.from_user.id, c.from_user.id, await _lang_of(c.from_user.id))
    await c.answer()


@router.callback_query(F.data == "gw:join")
async def gw_join(c: CallbackQuery) -> None:
    try:
        await shop.giveaway_join(c.from_user.id)
    except shop.ShopError as exc:
        msg = "Подпишитесь на канал и нажмите ещё раз" if exc.code == "not_subscribed" else "Конкурс выключен"
        return await c.answer(msg, show_alert=True)
    await c.answer(JOIN_OK.get(await _lang_of(c.from_user.id), JOIN_OK["en"]))
    try:
        await c.message.delete()
    except TelegramAPIError:
        pass
    await _gw_card(c.bot, c.from_user.id, c.from_user.id, await _lang_of(c.from_user.id))


# ── Звёзды ────────────────────────────────────────────────────────────

@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery) -> None:
    ok = False
    if q.invoice_payload.startswith("inv:") and q.invoice_payload[4:].isdigit():
        row = await db.get_invoice(int(q.invoice_payload[4:]))
        ok = bool(row and row["provider"] == "stars" and row["status"] in ("new", "expired")
                  and int(row["user_id"]) == q.from_user.id and int(row["amount"]) == q.total_amount)
    await q.answer(ok=ok, error_message=None if ok else "Счёт устарел, создайте новый в приложении")


@router.message(F.successful_payment)
async def paid(m: Message) -> None:
    sp = m.successful_payment
    if not sp.invoice_payload.startswith("inv:"):
        return
    if not sp.invoice_payload[4:].isdigit() or len(sp.invoice_payload) > 20:
        return
    inv_id = int(sp.invoice_payload[4:])
    row = await db.get_invoice(inv_id)
    # Сверяем, что заплатил тот, кому выставлен счёт, ровно столько и в звёздах.
    if (row is None or row["provider"] != "stars" or int(row["user_id"]) != m.from_user.id
            or sp.currency != "XTR" or int(row["amount"]) != sp.total_amount):
        log.error("звёзды: несовпадение счёта #%s: %s", inv_id, sp)
        await shop._admin_note(f"{_e('🛡')} Оплата звёздами не совпала со счётом #{inv_id} — проверьте вручную\n"  # noqa: SLF001
                               f"{await shop.who(m.from_user.id)}")
        return
    # Звёзды списаны — счёт зачисляем, даже если он успел «просрочиться».
    await db.run("UPDATE invoices SET status='new', external_id=? WHERE id=? AND provider='stars' "
                 "AND status='expired'", (sp.telegram_payment_charge_id, inv_id))
    import crypto
    await crypto.credit(inv_id)


# ── Уведомления из магазина ───────────────────────────────────────────

async def notify(uid: int, kind: str, **kw) -> None:
    lang = await _lang_of(uid)
    marks = {"done": "✅", "refund": "↩️", "won": "🏆", "topup": "💳", "received": "🎁", "ref_new": "👥"}
    if "name" in kw:
        kw["name"] = html.escape(str(kw["name"]))
    text = f"{_e(marks.get(kind, '🔔'))} {i18n.t(kind, lang, **kw)}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[_btn(i18n.t("open", lang), "📱", web_app=_webapp("?tab=orders"))]]) \
        if config.webapp_enabled() else None
    try:
        await shop.bot.send_message(uid, text, reply_markup=kb)
    except TelegramAPIError as exc:
        if isinstance(exc, TelegramForbiddenError):
            await db.run("UPDATE users SET blocked=1 WHERE id=?", (uid,))
            return
        await shop.bot.send_message(uid, _plain(text))


async def broadcast(key: str, **kw) -> int:
    """Рассылка на языке каждого человека. ~20 сообщений в секунду."""
    sent = 0
    for u in await db.all_("SELECT id, lang FROM users WHERE blocked=0"):
        lang = i18n.pick(u["lang"])
        kb = InlineKeyboardMarkup(inline_keyboard=[[_btn(i18n.t("gw", lang), "🎁", callback_data="gw")]])
        try:
            await shop.bot.send_message(u["id"], f"{_e('🎁')} {html.escape(i18n.t(key, lang, **kw))}", reply_markup=kb)
            sent += 1
        except TelegramForbiddenError:
            await db.run("UPDATE users SET blocked=1 WHERE id=?", (u["id"],))
        except TelegramAPIError as exc:
            log.debug("рассылка %s: %s", u["id"], exc)
        await asyncio.sleep(0.05)
    return sent


# ── Админка ───────────────────────────────────────────────────────────

def _is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


ADMIN_HELP = (
    "<b>Команды</b>\n"
    "/admin — статистика\n"
    "/promo RUS 5 — акция −5% на страну (0 — снять)\n"
    "/give 123456 100 — начислить ₽ (минус — списать)\n"
    "/code SALE 50 100 — промокод на 50 ₽, 100 активаций\n"
    "/whois +79991234567 — кому выдан номер (жалобы на спам)\n"
    "/ban 123456 причина — запретить покупки, /unban 123456\n"
    "/draw — провести конкурс дня сейчас\n"
    "/reserve — докупить резерв сейчас\n"
    "/emoji — создать/обновить свой набор премиум-эмодзи\n"
    "/broadcast текст — рассылка всем\n"
    "/emoji_list — какие премиум-эмодзи найдены, /emoji_set 📱 + премиум — заменить"
)


async def admin_old(m: Message) -> None:  # заменено панелью adminpanel.py (/admin)
    if not _is_admin(m.from_user.id):
        return
    day = await db.stats(int(time.time()) - 86400)
    alltime = await db.stats(0)
    bal = await __import__("lzt").balance()
    promos = await db.promos()
    f = shop.money
    await m.answer(
        f"<b>{config.BRAND}</b>{' · ДЕМО (без LZT_TOKEN)' if config.LZT_DEMO else ''}\n\n"
        f"<b>24 часа</b>: продаж {day['orders']} · выручка {f(day['revenue'])} · маржа {f(day['margin'])}\n"
        f"пополнений {f(day['topups'])} · новых людей {day['new_users']} · конкурс {f(day['giveaway_cost'])}\n\n"
        f"<b>Всё время</b>: продаж {alltime['orders']} · выручка {f(alltime['revenue'])} · маржа {f(alltime['margin'])}\n"
        f"людей {alltime['users']} · на балансах {f(alltime['balances'])}\n\n"
        f"Резерв: {alltime['reserve']} шт на {f(alltime['reserve_cost'])}\n"
        f"Баланс LZT: {'—' if bal is None else f'{bal:.2f} ₽'}\n"
        f"Наценка: {config.MARKUP * 100:.0f}% · звёзды ×{config.STARS_MARKUP:g}\n"
        f"Акции: {', '.join(f'{c} −{p}%' for c, p in promos.items()) or 'нет'}\n\n{ADMIN_HELP}"
    )


@router.message(Command("promo"))
async def promo(m: Message, command: CommandObject) -> None:
    if not _is_admin(m.from_user.id):
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) > 50:
        return await m.answer("Формат: /promo RUS 5 (скидка 0–50%)")
    await db.set_promo(parts[0].upper(), int(parts[1]))
    await m.answer(f"Готово: {parts[0].upper()} −{parts[1]}%. Цена не опустится ниже закупки + 1 ₽.")


@router.message(Command("give"))
async def give(m: Message, command: CommandObject) -> None:
    if not _is_admin(m.from_user.id):
        return
    parts = (command.args or "").split()
    try:
        uid, rub = int(parts[0]), float(parts[1])
    except (IndexError, ValueError):
        return await m.answer("Формат: /give 123456 100")
    if not await db.get_user(uid):
        return await m.answer("Такого человека нет в базе")
    left = await db.add_kop(uid, int(round(rub * 100)), "admin", f"by {m.from_user.id}")
    await m.answer(f"Баланс {uid}: {shop.money(left)}")


@router.message(Command("code"))
async def code_cmd(m: Message, command: CommandObject) -> None:
    if not _is_admin(m.from_user.id):
        return
    parts = (command.args or "").split()
    try:
        code, rub, uses = parts[0], float(parts[1]), int(parts[2])
    except (IndexError, ValueError):
        return await m.answer("Формат: /code SALE 50 100 (код, ₽, активаций)")
    await db.create_promo(code, int(round(rub * 100)), uses)
    await m.answer(f"Промокод <code>{html.escape(code.upper())}</code>: {rub:g} ₽ × {uses} активаций "
                   f"= до {rub * uses:g} ₽ из вашего кармана.")


@router.message(Command("whois"))
async def whois_cmd(m: Message, command: CommandObject) -> None:
    if not _is_admin(m.from_user.id):
        return
    rows = await db.whois(command.args or "")
    if not rows:
        return await m.answer("Такой номер мы не выдавали (или формат не тот: /whois +79991234567)")
    lines = []
    for r in rows:
        who = f"@{r['username']}" if r["username"] else html.escape(r["name"] or "")
        ban = " · <b>забанен</b>" if r["banned"] else ""
        lines.append(f"#{r['id']} {r['phone']} → {who} <code>{r['user_id']}</code>{ban}\n"
                     f"    {time.strftime('%d.%m.%Y %H:%M', time.localtime(r['created_at']))} · LZT {r['item_id']}")
    await m.answer("\n".join(lines) + "\n\nЗабанить: <code>/ban ID причина</code>")


@router.message(Command("ban"))
async def ban_cmd(m: Message, command: CommandObject) -> None:
    if not _is_admin(m.from_user.id):
        return
    parts = (command.args or "").split(maxsplit=1)
    if not parts or not parts[0].isdigit():
        return await m.answer("Формат: /ban 123456 причина")
    ok = await db.set_ban(int(parts[0]), parts[1] if len(parts) > 1 else "нарушение условий")
    await m.answer("Забанен: покупки, переводы и конкурсы закрыты." if ok else "Нет такого человека")


@router.message(Command("trust", "untrust"))
async def trust_cmd(m: Message, command: CommandObject) -> None:
    if not _is_admin(m.from_user.id) or not (command.args or "").strip().isdigit():
        return
    on = command.command == "trust"
    await db.run("UPDATE users SET trusted=? WHERE id=?", (1 if on else 0, int(command.args.strip())))
    await m.answer("Доверенный: без лимита покупок" if on else "Снят флаг доверенного")


@router.message(Command("unban"))
async def unban_cmd(m: Message, command: CommandObject) -> None:
    if not _is_admin(m.from_user.id):
        return
    if (command.args or "").strip().isdigit():
        await db.set_ban(int(command.args.strip()), "")
        await m.answer("Разбанен")


@router.message(Command("terms", "privacy"))
async def legal_cmd(m: Message, command: CommandObject) -> None:
    kind = "terms" if command.command == "terms" else "privacy"
    lang = "ru" if (await _lang_of(m.from_user.id)) == "ru" else "en"
    if config.webapp_enabled():
        return await m.answer(f"{config.WEBAPP_URL}/{kind}?lang={lang}")
    import re
    body = (config.BASE_DIR / "webapp" / "legal" / f"{kind}.{lang}.html").read_text(encoding="utf-8")
    text = re.sub(r"<h2>(.*?)</h2>", r"<b>\1</b>", body)
    text = re.sub(r"<h3>(.*?)</h3>", r"\n<b>\1</b>", text)
    text = re.sub(r"<li>", "• ", text)
    text = re.sub(r"</?(ul|li|p|span)[^>]*>", "", text)
    text = re.sub(r'<p class="legal-date">', "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    for i in range(0, len(text), 3800):
        await m.answer(text[i:i + 3800], disable_web_page_preview=True)


@router.message(Command("draw"))
async def draw_now(m: Message) -> None:
    if _is_admin(m.from_user.id):
        await m.answer(str(await shop.draw(force=True)))


@router.message(Command("reserve"))
async def reserve_now(m: Message) -> None:
    if _is_admin(m.from_user.id):
        await shop.keep_reserve()
        await m.answer(f"Резерв: {len(await db.reserve_ready())} шт")


@router.message(Command("emoji_set"))
async def emoji_set(m: Message) -> None:
    """/emoji_set 📱 <премиум-эмодзи> — какой премиум ставить вместо символа. Без премиума — сброс."""
    if not _is_admin(m.from_user.id):
        return
    parts = (m.text or "").split(maxsplit=2)
    if len(parts) < 2:
        return await m.answer("Формат: /emoji_set 📱 и сразу премиум-эмодзи, которым его заменить")
    ch = parts[1][:4]
    cid = next((e.custom_emoji_id for e in (m.entities or []) if e.type == "custom_emoji"), "")
    await emoji.set_manual(ch, cid or "")
    await m.answer(f"Готово: {_e(ch) or 'сброшено'}" if cid else "Замена сброшена")


@router.message(Command("emoji_list"))
async def emoji_list(m: Message) -> None:
    if not _is_admin(m.from_user.id):
        return
    have = [f"{_e(ch)} {emoji.SOURCES.get(ch, '')}" for ch in emoji.USED if emoji.get(ch)]
    miss = [ch for ch in emoji.USED if not emoji.get(ch)]
    text = (f"<b>Премиум-эмодзи</b>: пак {html.escape(emoji.PACK)} + свой набор\n\n" + "  ".join(have)
            + (f"\n\n<b>Нет премиума</b> (на этих местах пусто): {' '.join(miss)}\n"
               "Назначить: <code>/emoji_set 📱</code> + премиум-эмодзи" if miss else ""))
    try:
        await m.answer(text)
    except TelegramAPIError:
        await m.answer(_plain(text))


@router.message(Command("emoji"))
async def emoji_cmd(m: Message) -> None:
    if _is_admin(m.from_user.id):
        ok, text = await emoji.create(m.bot, m.from_user.id, recreate="re" in (m.text or ""))
        await m.answer(text)


@router.message(Command("broadcast"))
async def bc(m: Message, command: CommandObject) -> None:
    if not _is_admin(m.from_user.id) or not command.args:
        return
    n = 0
    for u in await db.all_("SELECT id FROM users WHERE blocked=0"):
        try:
            await m.bot.send_message(u["id"], command.args)
            n += 1
        except TelegramForbiddenError:
            await db.run("UPDATE users SET blocked=1 WHERE id=?", (u["id"],))
        except TelegramAPIError:
            pass
        await asyncio.sleep(0.05)
    await m.answer(f"Отправлено: {n}")
