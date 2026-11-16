"""Прогон текстовой версии без Telegram: python tools/test_textmode.py

Апдейты идут через настоящий Dispatcher aiogram, а запросы к Bot API
перехватывает подменённая сессия — она запоминает, что бот отправил.
База временная, LZT в демо-режиме.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.update(MAX_PER_DAY_NEW="50", LZT_DEMO="1", CHANNEL="", RESERVE_SIZE="0", BOT_TOKEN="1:TEST", WEBAPP_URL="",
                  DB_PATH=str(Path(tempfile.mkdtemp()) / "t.db"))
sys.path.insert(0, str(ROOT))

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import AnswerCallbackQuery, CreateInvoiceLink, GetChatMember  # noqa: E402
from aiogram.types import CallbackQuery, Chat, ChatMemberMember, Message, Update, User  # noqa: E402

import bot as botmod  # noqa: E402
import db  # noqa: E402
import shop  # noqa: E402
import textmode  # noqa: E402

SENT: list[tuple[str, str, object]] = []
FAILS: list[str] = []


class FakeSession(BaseSession):
    async def make_request(self, bot, method, timeout=None):
        name = type(method).__name__
        text = getattr(method, "text", None) or getattr(method, "caption", None) or ""
        SENT.append((name, text, getattr(method, "reply_markup", None)))
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, CreateInvoiceLink):
            return "https://t.me/$invoice"
        if isinstance(method, GetChatMember):
            return ChatMemberMember(user=User(id=1, is_bot=False, first_name="x"))
        return Message(message_id=len(SENT), date=dt.datetime.now(), chat=Chat(id=1, type="private"), text=text or "x")

    async def close(self):
        pass

    async def stream_content(self, *a, **k):
        if False:
            yield b""


def user(uid: int) -> User:
    return User(id=uid, is_bot=False, first_name=f"U{uid}", username=f"u{uid}", language_code="ru")


n = 0


def upd_msg(uid: int, text: str) -> Update:
    global n
    n += 1
    return Update(update_id=n, message=Message(message_id=n, date=dt.datetime.now(), chat=Chat(id=uid, type="private"),
                                                from_user=user(uid), text=text))


def upd_cb(uid: int, data: str) -> Update:
    global n
    n += 1
    msg = Message(message_id=n, date=dt.datetime.now(), chat=Chat(id=uid, type="private"), text="x")
    return Update(update_id=n, callback_query=CallbackQuery(id=str(n), from_user=user(uid), chat_instance="c",
                                                            message=msg, data=data))


def last_text() -> str:
    for name, text, _ in reversed(SENT):
        if text:
            return text
    return ""


def buttons() -> list[str]:
    for name, _, markup in reversed(SENT):
        if markup is not None and getattr(markup, "inline_keyboard", None):
            return [btn.callback_data or btn.url or "" for row in markup.inline_keyboard for btn in row]
    return []


def check(name: str, cond: bool) -> None:
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILS.append(name)


async def main() -> None:
    await db.init()
    bot = Bot("1:TEST", session=FakeSession())
    shop.bot = bot
    dp = Dispatcher()
    dp.include_router(botmod.router)
    dp.include_router(textmode.router)
    for c3 in ("RUS", "USA", "DEU"):
        await shop.refresh_country(c3)

    async def go(u: Update) -> None:
        await dp.feed_update(bot, u)

    await go(upd_msg(1, "/start"))
    await go(upd_msg(2, "/start"))
    check("/start: в меню есть «Каталог» и «Профиль»", "tm:cat:all:0" in buttons() and "tm:p" in buttons())
    await db.add_kop(1, 50_000, "admin")

    await go(upd_cb(1, "tm:cat:all:0"))
    check("каталог: страны кнопками", any(x.startswith("tm:c:RUS") for x in buttons()))
    await go(upd_cb(1, "tm:cat:eu:0"))
    check("регион Европа: есть Германия, нет России",
          any(x.startswith("tm:c:DEU") for x in buttons()) and not any(x.startswith("tm:c:RUS") for x in buttons()))

    await go(upd_cb(1, "tm:c:RUS:cheap:0"))
    lots = [x for x in buttons() if x.startswith("tm:l:")]
    check(f"страна: лоты страницами (≤{textmode.PER_L})", 0 < len(lots) <= textmode.PER_L)
    check("есть листание страниц", any(x.startswith("tm:c:RUS:cheap:1") for x in buttons()))

    await go(upd_cb(1, lots[0]))
    check("карточка лота с ценой", "Купить" in str([b for b in SENT[-2:]]) or any(x.startswith("tm:bq:") for x in buttons()))
    bq = next(x for x in buttons() if x.startswith("tm:bq:"))
    await go(upd_cb(1, bq))
    acc = [x for x in buttons() if x.startswith("tm:acc:")]
    check("перед первой покупкой — принять условия", bool(acc) and "спама" in last_text())
    await go(upd_cb(1, acc[0]))
    check("после согласия — снова карточка лота", any(x.startswith("tm:bq:") for x in buttons()))
    await go(upd_cb(1, bq))
    b_ = next(x for x in buttons() if x.startswith("tm:b:"))
    before = (await db.get_user(1))["kop"]
    await go(upd_cb(1, b_))
    check("покупка: «Покупаем на маркете…»", "Покупаем" in last_text())
    for _ in range(40):
        o = (await db.user_orders(1))[0]
        if o["status"] != "pending":
            break
        await asyncio.sleep(0.1)
    o = (await db.user_orders(1))[0]
    check("заказ выполнен или возвращён (демо: 5 % отказов)", o["status"] in ("done", "refunded"))
    check("списали ровно цену (или вернули)", (await db.get_user(1))["kop"] in (before - o["price_kop"], before))

    await go(upd_cb(1, "tm:o:0"))
    check("мои покупки: заказ в списке", f"tm:od:{o['id']}" in buttons())
    await go(upd_cb(1, f"tm:od:{o['id']}"))
    if o["status"] == "done":
        check("карточка заказа: номер и кнопка кода", o["phone"] in last_text() and f"tm:code:{o['id']}" in buttons())
        await go(upd_cb(1, f"tm:code:{o['id']}"))
        check("код входа пришёл", "Код входа" in last_text())

    await go(upd_cb(1, "tm:p"))
    check("профиль: баланс и кнопки", "Баланс" in last_text() and "tm:t" in buttons() and "tm:r" in buttons())
    await go(upd_cb(1, "tm:t"))
    check("пополнение: суммы", "tm:ta:250" in buttons())
    await go(upd_cb(1, "tm:ta:250"))
    check("способы оплаты: звёзды", "tm:pay:stars:250" in buttons())
    await go(upd_cb(1, "tm:pay:stars:250"))
    check("звёзды: ссылка на счёт", any("$invoice" in x for x in buttons()))
    await go(upd_cb(1, "tm:tc"))
    await go(upd_msg(1, "300"))
    check("своя сумма 300 → способы оплаты", "tm:pay:stars:300" in buttons())

    b1 = (await db.get_user(1))["kop"]
    await go(upd_cb(1, "tm:s"))
    await go(upd_msg(1, "@u2 15"))
    check("перевод другу 15 ₽", (await db.get_user(1))["kop"] == b1 - 1500 and (await db.get_user(2))["kop"] == 1500)

    await db.create_promo("TXT", 700, 5)
    await go(upd_cb(1, "tm:pr"))
    await go(upd_msg(1, "txt"))
    check("промокод +7 ₽", "+7" in last_text())
    await go(upd_msg(1, "просто текст"))
    check("свободный текст без ожидания — бот молчит", "+7" in last_text())

    await go(upd_cb(1, "tm:r"))
    check("друзья: ссылка и прогресс", "ref1" in last_text() or "start=ref1" in last_text())

    await db.reserve_add(555, "RUS", 2000, "+79990005555", "", {})
    await go(upd_cb(1, "tm:c:RUS:cheap:0"))
    check("есть кнопка мгновенной выдачи", "tm:bi:RUS" in buttons())
    await go(upd_cb(1, "tm:bi:RUS"))
    check("мгновенная выдача: номер сразу", "+79990005555" in last_text())

    await go(upd_cb(1, "tm:legal:terms"))
    check("условия открываются текстом в чате", "Условия использования" in "".join(t for _, t, _ in SENT[-4:]))

    await db.close()
    await bot.session.close()
    print()
    print("ТЕКСТОВАЯ ВЕРСИЯ: ВСЁ В ПОРЯДКЕ" if not FAILS else f"ОШИБКИ: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
