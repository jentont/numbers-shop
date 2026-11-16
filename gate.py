"""Обязательная подписка на канал: без неё бот и Mini App не работают.

Включена, когда SUB_REQUIRED=1 и задан CHANNEL (бот должен быть админом
канала). Админы проходят всегда. Оплата звёздами, /terms и /privacy
пропускаются, чтобы деньги не потерялись и документы были доступны.

Если Telegram не даёт проверить подписку (бот не админ канала, канал
переименовали) — людей не блокируем, а один раз пишем админу: иначе
одна ошибка в настройках закрыла бы магазин для всех.
"""
from __future__ import annotations

import html
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject

import config
import db
import i18n

log = logging.getLogger("numbers.gate")
router = Router(name="gate")

#: Что человек хотел сделать до подписки: после проверки продолжим (/start gw).
PENDING: dict[int, str] = {}

TXT = {
    "ru": ("<b>Подпишитесь на наш канал</b>\n\nБот и маркет работают только для подписчиков канала "
           "{ch}. Подпишитесь и нажмите «Проверить подписку».", "Подписаться", "Проверить подписку",
           "Вы ещё не подписались на канал"),
    "en": ("<b>Subscribe to our channel</b>\n\nThe bot and the market are available to subscribers of "
           "{ch} only. Subscribe and tap “Check subscription”.", "Subscribe", "Check subscription",
           "You haven't subscribed to the channel yet"),
    "es": ("<b>Suscríbete a nuestro canal</b>\n\nEl bot y el mercado solo están disponibles para los "
           "suscriptores de {ch}. Suscríbete y pulsa «Comprobar suscripción».", "Suscribirse",
           "Comprobar suscripción", "Aún no te has suscrito al canal"),
    "ar": ("<b>اشترك في قناتنا</b>\n\nالبوت والمتجر متاحان لمشتركي {ch} فقط. اشترك ثم اضغط «تحقق من الاشتراك».",
           "اشترك", "تحقق من الاشتراك", "لم تشترك في القناة بعد"),
    "hi": ("<b>हमारे चैनल को सब्सक्राइब करें</b>\n\nबॉट और मार्केट केवल {ch} के सब्सक्राइबर्स के लिए हैं। "
           "सब्सक्राइब करें और «सब्सक्रिप्शन जाँचें» दबाएँ।", "सब्सक्राइब करें", "सब्सक्रिप्शन जाँचें",
           "आपने अभी चैनल सब्सक्राइब नहीं किया"),
    "zh": ("<b>请订阅我们的频道</b>\n\n机器人和商城仅对 {ch} 的订阅者开放。订阅后点击「检查订阅」。",
           "订阅", "检查订阅", "你还没有订阅频道"),
}


def active() -> bool:
    return bool(config.SUB_REQUIRED and config.CHANNEL)


def texts(lang: str) -> tuple:
    return TXT.get(i18n.pick(lang), TXT["en"])


def markup(lang: str) -> InlineKeyboardMarkup:
    import bot as b
    _, sub, check, _ = texts(lang)
    rows = []
    if config.CHANNEL_URL:
        rows.append([b._btn(sub, "📢", url=config.CHANNEL_URL, style="primary")])
    rows.append([b._btn(check, "✅", callback_data="sub:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send(bot, chat_id: int, lang: str) -> None:
    import bot as b
    text = f"{b._e('📢')} " + texts(lang)[0].format(ch=html.escape(config.CHANNEL))
    try:
        await bot.send_message(chat_id, text, reply_markup=markup(lang))
    except TelegramAPIError:
        await bot.send_message(chat_id, b._plain(text), reply_markup=markup(lang))


async def lang_of(uid: int) -> str:
    u = await db.get_user(uid)
    return i18n.pick(u["lang"] if u else "en")


class SubGate(BaseMiddleware):
    """Пропускает к хендлерам только подписчиков (и админов)."""

    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]],
                       event: TelegramObject, data: dict) -> Any:
        if not active():
            return await handler(event, data)
        user = data.get("event_from_user")
        if user is None or user.id in config.ADMIN_IDS:
            return await handler(event, data)
        if isinstance(event, Message):
            if event.chat.type != "private" or event.successful_payment:
                return await handler(event, data)
            text = event.text or ""
            # /start сам решает: сначала регистрирует и привязывает реферала, потом показывает шлюз.
            if text.startswith(("/start", "/terms", "/privacy")):
                return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "sub:check":
            return await handler(event, data)
        import shop
        if await shop.is_subscribed(user.id):
            return await handler(event, data)
        lang = await lang_of(user.id)
        if isinstance(event, CallbackQuery):
            try:
                await event.answer(texts(lang)[3], show_alert=True)
            except TelegramAPIError:
                pass
            await send(event.bot, user.id, lang)
        else:
            await send(event.bot, event.chat.id, lang)
        return None


@router.callback_query(F.data == "sub:check")
async def check(c: CallbackQuery) -> None:
    import bot as b
    import shop
    shop.forget_sub(c.from_user.id)          # перепроверяем по-настоящему, без кэша
    lang = await lang_of(c.from_user.id)
    if active() and not await shop.is_subscribed(c.from_user.id):
        return await c.answer(texts(lang)[3], show_alert=True)
    await c.answer()
    try:
        await c.message.delete()
    except TelegramAPIError:
        pass
    u = await db.get_user(c.from_user.id)
    await b._send(c.bot, c.from_user.id, b.menu_text(lang, c.from_user.first_name, int(u["kop"]) if u else 0),
                  b.menu_kb, lang)
    if PENDING.pop(c.from_user.id, "") == "gw":
        await b._gw_card(c.bot, c.from_user.id, c.from_user.id, lang)


def setup(dp) -> None:
    dp.message.outer_middleware(SubGate())
    dp.callback_query.outer_middleware(SubGate())
    dp.include_router(router)

