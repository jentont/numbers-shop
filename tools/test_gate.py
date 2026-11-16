"""Обязательная подписка и «никаких обычных эмодзи»: python tools/test_gate.py"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.update(LZT_DEMO="1", CHANNEL="@solutions_test", SUB_REQUIRED="1", RESERVE_SIZE="0", BOT_TOKEN="1:TEST",
                  WEBAPP_URL="", DEV_AUTH="1", ADMIN_IDS="777", DB_PATH=str(Path(tempfile.mkdtemp()) / "g.db"))
sys.path.insert(0, str(ROOT))

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import AnswerCallbackQuery, GetChatMember  # noqa: E402
from aiogram.types import (CallbackQuery, Chat, ChatMemberLeft, ChatMemberMember, Message, Update,  # noqa: E402
                           User)
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import adminpanel  # noqa: E402
import bot as botmod  # noqa: E402
import db  # noqa: E402
import emoji  # noqa: E402
import gate  # noqa: E402
import shop  # noqa: E402
import textmode  # noqa: E402
import web  # noqa: E402

SENT: list[tuple[str, str, object, dict]] = []
UNSUB = {1, 2}
BROKEN = {"on": False}
FAILS: list[str] = []
EMO = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿]")


class FakeSession(BaseSession):
    async def make_request(self, bot, method, timeout=None):
        name = type(method).__name__
        text = getattr(method, "text", None) or getattr(method, "caption", None) or ""
        SENT.append((name, text, getattr(method, "reply_markup", None), method.model_dump()))
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, GetChatMember):
            if BROKEN["on"]:
                from aiogram.exceptions import TelegramBadRequest
                raise TelegramBadRequest(method=method, message="Bad Request: member list is inaccessible")
            u = User(id=method.user_id, is_bot=False, first_name="x")
            return ChatMemberLeft(user=u) if method.user_id in UNSUB else ChatMemberMember(user=u)
        return Message(message_id=len(SENT), date=dt.datetime.now(), chat=Chat(id=1, type="private"), text=text or "x")

    async def close(self):
        pass

    async def stream_content(self, *a, **k):
        if False:
            yield b""


n = 0


def user(uid):
    return User(id=uid, is_bot=False, first_name=f"U{uid}", username=f"u{uid}", language_code="ru")


def msg(uid, text):
    global n
    n += 1
    return Update(update_id=n, message=Message(message_id=n, date=dt.datetime.now(), chat=Chat(id=uid, type="private"),
                                                from_user=user(uid), text=text))


def cb(uid, data):
    global n
    n += 1
    m = Message(message_id=n, date=dt.datetime.now(), chat=Chat(id=uid, type="private"), text="x")
    return Update(update_id=n, callback_query=CallbackQuery(id=str(n), from_user=user(uid), chat_instance="c",
                                                            message=m, data=data))


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILS.append(name)


def last_text():
    return next((t for _, t, _, _ in reversed(SENT) if t), "")


def buttons():
    for _, _, mk, _ in reversed(SENT):
        if mk is not None and getattr(mk, "inline_keyboard", None):
            return [b.callback_data or b.url or "" for row in mk.inline_keyboard for b in row]
    return []


def alerts():
    return [d.get("text") or "" for name, _, _, d in SENT if name == "AnswerCallbackQuery" and d.get("show_alert")]


async def main():
    await db.init()
    bot = Bot("1:TEST", session=FakeSession())
    shop.bot = bot
    dp = Dispatcher()
    gate.setup(dp)
    dp.include_router(adminpanel.router)
    dp.include_router(botmod.router)
    dp.include_router(textmode.router)
    go = lambda u: dp.feed_update(bot, u)  # noqa: E731
    for c3 in ("RUS", "USA"):
        await shop.refresh_country(c3)

    print("Бот")
    await go(msg(5, "/start"))                        # пригласивший (подписан)
    await go(msg(1, "/start ref5"))
    check("без подписки /start → «Подпишитесь на наш канал»", "Подпишитесь" in last_text())
    check("кнопки «Подписаться» и «Проверить подписку»", "sub:check" in buttons()
          and any("t.me/solutions_test" in b for b in buttons()))
    check("реферал привязан ещё до подписки", (await db.get_user(1))["ref_by"] == 5)
    before = len(SENT)
    await go(cb(1, "tm:cat:all:0"))
    check("без подписки каталог не открывается", not any("tm:c:" in str(m) for _, _, m, _ in SENT[before:]))
    check("кнопка без подписки → предупреждение", any("не подписались" in a for a in alerts()))
    await go(cb(1, "sub:check"))
    check("«Проверить» без подписки → «Вы ещё не подписались»", "не подписались" in alerts()[-1])
    UNSUB.discard(1)
    await go(cb(1, "sub:check"))
    check("после подписки — главное меню", "tm:cat:all:0" in buttons())
    await go(cb(1, "tm:cat:all:0"))
    check("после подписки каталог работает", any(b.startswith("tm:c:") for b in buttons()))
    await go(msg(777, "/start"))
    check("админ проходит без подписки", "tm:cat:all:0" in buttons())
    BROKEN["on"] = True
    shop.forget_sub(2)
    await go(msg(2, "/start"))
    check("бот не админ канала → людей не блокируем", "tm:cat:all:0" in buttons())
    check("и админу пришло предупреждение", any("Не могу проверить подписку" in t for _, t, _, _ in SENT))
    BROKEN["on"] = False

    print("Mini App / API")
    client = TestClient(TestServer(web.app()))
    await client.start_server()
    UNSUB.add(3)
    H = {"X-Dev": "3", "Content-Type": "application/json"}
    r = await client.get("/api/me", headers=H)
    me = await r.json()
    check("/api/me сообщает need_sub", r.status == 200 and me["need_sub"] is True)
    r = await client.get("/api/home", headers=H)
    check("без подписки API закрыт (403 need_sub)", r.status == 403 and (await r.json())["error"] == "need_sub")
    r = await client.post("/api/sub", headers=H, data="{}")
    check("/api/sub без подписки → need_sub", (await r.json())["need_sub"] is True)
    UNSUB.discard(3)
    r = await client.post("/api/sub", headers=H, data="{}")
    check("после подписки /api/sub → можно", (await r.json())["need_sub"] is False)
    r = await client.get("/api/home", headers=H)
    check("после подписки API открыт", r.status == 200)
    await client.close()

    print("Никаких обычных эмодзи")
    plain = []
    for name, text, mk, _ in SENT:
        clean = re.sub(r"<tg-emoji[^>]*>.*?</tg-emoji>", "", text or "")
        if EMO.search(clean):
            plain.append(clean[:60])
        for row in getattr(mk, "inline_keyboard", None) or []:
            for b_ in row:
                if EMO.search(b_.text):
                    plain.append("кнопка: " + b_.text)
    check(f"в {len(SENT)} отправках нет обычных эмодзи", not plain)
    for p in plain[:5]:
        print("     ", p)
    emoji.ID["📢"] = "5368324170671202286"
    k = gate.markup("ru").inline_keyboard[0][0]
    check("с премиумом — иконка на кнопке, в тексте кнопки эмодзи нет",
          k.icon_custom_emoji_id == "5368324170671202286" and not EMO.search(k.text))
    check("_e без премиума — пусто", botmod._e("🦄") == "")

    await db.close()
    await bot.session.close()
    print()
    print("ПОДПИСКА И ЭМОДЗИ: ВСЁ В ПОРЯДКЕ" if not FAILS else f"ОШИБКИ: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
