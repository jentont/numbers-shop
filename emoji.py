"""Премиум-эмодзи: везде только они, обычных эмодзи в боте нет.

Откуда берутся (по приоритету):
1. Ручные замены админа: /emoji_set 📱 <премиум-эмодзи> — хранятся в settings.emoji_map.
2. Пак владельца t.me/addemoji/tgiosicons (EMOJI_PACK): символ эмодзи → custom_emoji_id.
3. Свой белый набор numbers_icons_by_<бот> (assets/emoji, создаётся командой /emoji).

Если для символа нет премиум-эмодзи ни в одном источнике, на его месте
ничего не выводится — ни в тексте, ни на кнопке. Обычный эмодзи
вместо премиума не подставляется никогда.
"""
from __future__ import annotations

import html
import json
import logging
import os

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, InputSticker

import config

log = logging.getLogger("numbers.emoji")
DIR = config.BASE_DIR / "assets" / "emoji"
TITLE = "Solutions Numbers"
PACK = os.getenv("EMOJI_PACK", "tgiosicons").strip()

#: файл своего набора → эмодзи, которыми его вставлять (первый — основной).
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

#: Все символы, которые бот использует, — для /emoji_list.
USED = sorted({c for v in MAP.values() for c in v} | {"⚠️", "💸", "✏️", "📤", "⏳", "❌", "🔍", "🏷️"})

ID: dict[str, str] = {}
SOURCES: dict[str, str] = {}      # символ → откуда взят (override / pack / own)


def _norm(ch: str) -> str:
    return ch.replace("️", "")


def get(ch: str) -> str | None:
    return ID.get(ch) or ID.get(_norm(ch))


def tag(ch: str) -> str:
    """HTML премиум-эмодзи или пустая строка, если его нет."""
    cid = get(ch)
    return f'<tg-emoji emoji-id="{cid}">{html.escape(ch)}</tg-emoji>' if cid else ""


def pack_name() -> str:
    return f"numbers_icons_by_{config.BOT_USERNAME}"


def pack_url() -> str:
    return f"https://t.me/addemoji/{pack_name()}"


async def _read(bot: Bot, name: str, source: str, into: dict[str, str]) -> int:
    try:
        pack = await bot.get_sticker_set(name)
    except TelegramAPIError as exc:
        log.info("эмодзи-пак %s недоступен: %s", name, exc)
        return 0
    n = 0
    for st in pack.stickers:
        if st.custom_emoji_id and st.emoji:
            for key in (st.emoji, _norm(st.emoji)):
                if key not in into:
                    into[key] = st.custom_emoji_id
                    SOURCES[key] = source
                    n += 1
    log.info("эмодзи-пак %s: %s стикеров", name, len(pack.stickers))
    return len(pack.stickers)


async def load(bot: Bot) -> int:
    """Собирает ID: ручные замены → пак tgiosicons → свой набор."""
    import db
    found: dict[str, str] = {}
    SOURCES.clear()
    try:
        manual = json.loads(await db.get_setting("emoji_map", "{}") or "{}")
    except ValueError:
        manual = {}
    for ch, cid in manual.items():
        found[ch] = str(cid)
        found[_norm(ch)] = str(cid)
        SOURCES[ch] = SOURCES[_norm(ch)] = "override"
    total = 0
    if PACK:
        total += await _read(bot, PACK, "pack", found)
    if config.BOT_USERNAME:
        total += await _read(bot, pack_name(), "own", found)
    ID.clear()
    ID.update(found)
    return total


async def set_manual(ch: str, cid: str) -> None:
    import db
    try:
        manual = json.loads(await db.get_setting("emoji_map", "{}") or "{}")
    except ValueError:
        manual = {}
    if cid:
        manual[ch] = cid
    else:
        manual.pop(ch, None)
    await db.set_setting("emoji_map", json.dumps(manual, ensure_ascii=False))
    if cid:
        ID[ch] = ID[_norm(ch)] = cid
        SOURCES[ch] = SOURCES[_norm(ch)] = "override"
    else:
        ID.pop(ch, None)


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
