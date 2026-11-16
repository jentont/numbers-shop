"""Свой набор премиум-эмодзи Solutions Numbers.

Картинки — assets/emoji/*.png (100×100): чёрный глиф на белой плитке,
белый стиль бренда. Рисует их tools/make_emoji.py из тех же иконок,
что в витрине. needs_repainting выключен: плитка белая в любой теме.

Создать набор может только бот (createNewStickerSet), имя кончается на
_by_<username бота>, владелец — админ, который уже писал боту.
ID эмодзи бот читает из набора при старте и кладёт в ID: символ → id.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, InputSticker

import config

log = logging.getLogger("numbers.emoji")
DIR = config.BASE_DIR / "assets" / "emoji"
TITLE = "Solutions Numbers"

#: файл → эмодзи, которыми его вставлять (первый — основной).
MAP = {
    "phone": ["📱"], "sim": ["📶"], "cart": ["🛒"], "globe": ["🌐", "🌍"], "bolt": ["⚡"],
    "gift": ["🎁"], "card": ["💳"], "wallet": ["👛"], "star": ["⭐"], "flame": ["🔥"],
    "tag": ["🏷"], "box": ["📦"], "check": ["✅"], "lock": ["🔒"], "key": ["🔑"],
    "book": ["📖"], "chat": ["💬"], "crown": ["👑"], "user": ["👤"], "users": ["👥"],
    "down": ["👇"], "sparkles": ["✨"], "rocket": ["🚀"], "clock": ["⏰"], "hash": ["#️⃣"],
    "plus": ["➕"], "back": ["⬅️"], "chart": ["📊"], "trophy": ["🏆"], "bell": ["🔔"],
    "copy": ["📋"], "shield": ["🛡"], "gem": ["💎"], "coin": ["🪙"], "search": ["🔎"],
    "megaphone": ["📢"], "refund": ["↩️"], "wave": ["👋"], "s": ["🅢"],
}

ID: dict[str, str] = {}


def pack_name() -> str:
    return f"numbers_icons_by_{config.BOT_USERNAME}"


def pack_url() -> str:
    return f"https://t.me/addemoji/{pack_name()}"


async def load(bot: Bot) -> int:
    """Читает набор и заполняет ID. 0 — набора ещё нет."""
    try:
        pack = await bot.get_sticker_set(pack_name())
    except TelegramAPIError:
        return 0
    ID.clear()
    for st in pack.stickers:
        if st.custom_emoji_id and st.emoji:
            ID.setdefault(st.emoji, st.custom_emoji_id)
            ID.setdefault(st.emoji.replace("️", ""), st.custom_emoji_id)
    log.info("эмодзи-набор %s: %s шт", pack_name(), len(pack.stickers))
    return len(pack.stickers)


async def create(bot: Bot, owner_id: int, recreate: bool = False) -> tuple[bool, str]:
    files = sorted(DIR.glob("*.png"))
    if not files:
        return False, "Нет картинок в assets/emoji — запустите tools/make_emoji.py"
    try:
        exists = await bot.get_sticker_set(pack_name())
    except TelegramAPIError:
        exists = None
    if exists and not recreate:
        n = await load(bot)
        return True, f"Набор уже есть ({n} шт): {pack_url()}\nПересоздать: /emoji re"
    if exists:
        try:
            await bot.delete_sticker_set(pack_name())
        except TelegramAPIError as exc:
            return False, f"Не удалось удалить старый набор: {exc}"
    stickers = [InputSticker(sticker=FSInputFile(f), format="static", emoji_list=MAP.get(f.stem, ["⭐"]))
                for f in files][:50]
    try:
        await bot.create_new_sticker_set(user_id=owner_id, name=pack_name(), title=TITLE, stickers=stickers,
                                         sticker_type="custom_emoji", needs_repainting=False)
    except TelegramAPIError as exc:
        return False, f"Telegram не создал набор: {exc}"
    n = await load(bot)
    return True, f"Готово: {n} эмодзи — {pack_url()}\nКнопки и меню уже используют их."
