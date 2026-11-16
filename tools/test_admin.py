"""Прогон админ-панели без Telegram: python -X utf8 tools/test_admin.py

Апдейты идут через настоящий Dispatcher aiogram, а запросы к Bot API
перехватывает подменённая сессия — она запоминает каждый вызов.
База временная, LZT в демо-режиме.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN = 900
os.environ.update(LZT_DEMO="1", CHANNEL="", RESERVE_SIZE="0", BOT_TOKEN="1:TEST", WEBAPP_URL="",
                  ADMIN_IDS=str(ADMIN), DB_PATH=str(Path(tempfile.mkdtemp()) / "a.db"))
sys.path.insert(0, str(ROOT))

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import AnswerCallbackQuery  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User  # noqa: E402

import adminpanel as ap  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import shop  # noqa: E402

CALLS: list[object] = []
FAILS: list[str] = []


class FakeSession(BaseSession):
    async def make_request(self, bot, method, timeout=None):
        CALLS.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        text = getattr(method, "text", None) or getattr(method, "caption", None) or "x"
        chat = getattr(method, "chat_id", 1)
        chat = chat if isinstance(chat, int) else 1
        return Message(message_id=len(CALLS) + 10_000, date=dt.datetime.now(), chat=Chat(id=chat, type="private"),
                       text=text)

    async def close(self):
        pass

    async def stream_content(self, *a, **k):
        if False:
            yield b""


def user(uid: int) -> User:
    return User(id=uid, is_bot=False, first_name=f"U{uid}", username=f"u{uid}", language_code="ru")


n = 0


def upd_msg(uid: int, text: str, entities: list | None = None) -> Update:
    global n
    n += 1
    return Update(update_id=n, message=Message(message_id=n, date=dt.datetime.now(),
                                                chat=Chat(id=uid, type="private"), from_user=user(uid),
                                                text=text, entities=entities))


def upd_cb(uid: int, data: str) -> Update:
    global n
    n += 1
    msg = Message(message_id=n, date=dt.datetime.now(), chat=Chat(id=uid, type="private"), text="x")
    return Update(update_id=n, callback_query=CallbackQuery(id=str(n), from_user=user(uid), chat_instance="c",
                                                            message=msg, data=data))


def texts_since(i: int) -> str:
    return "\n".join((getattr(m, "text", None) or getattr(m, "caption", None) or "") for m in CALLS[i:])


def last_text() -> str:
    for m in reversed(CALLS):
        t = getattr(m, "text", None)
        if t:
            return t
    return ""


def buttons():
    for m in reversed(CALLS):
        mk = getattr(m, "reply_markup", None)
        if mk is not None and getattr(mk, "inline_keyboard", None):
            return [b for row in mk.inline_keyboard for b in row]
    return []


def cbs() -> list[str]:
    return [b.callback_data or b.url or "" for b in buttons()]


def check(name: str, cond: bool) -> None:
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILS.append(name)


async def seed() -> int:
    now = int(time.time())
    for uid, name, nick in ((1, "Алиса", "alice"), (2, "Боб <b>", "bob"), (3, "Карл", "carl")):
        await db.run("INSERT INTO users(id,name,username,lang,created_at) VALUES(?,?,?,?,?)",
                     (uid, name, nick, "ru", now - 3 * 86400 + uid))
    await db.run("UPDATE users SET ref_by=1, ref_ok=1 WHERE id=2")
    for uid in range(100, 110):   # заблокировали бота — для листания и чтобы не попасть в рассылку
        await db.run("INSERT INTO users(id,name,username,lang,blocked,created_at) VALUES(?,?,?,?,1,?)",
                     (uid, f"Гость{uid}", "", "ru", now - 86400 + uid))
    await db.add_kop(1, 50_000, "topup", "seed")
    inv = await db.create_invoice(1, "cryptobot", 50_000)
    await db.run("UPDATE invoices SET status='paid', paid_at=? WHERE id=?", (now, inv))
    oid = await db.create_order(2, "live", 777, "RUS", 2_800, 3_100)
    await db.finish_order(oid, "+79990001122", "", {})
    oid2 = await db.create_order(1, "reserve", 778, "USA", 6_000, 6_600)
    await db.finish_order(oid2, "+15550001111", "pw", {})
    return oid


async def main() -> None:
    await db.init()
    bot = Bot("1:TEST", session=FakeSession())
    shop.bot = bot
    dp = Dispatcher()
    dp.include_router(ap.router)
    oid = await seed()

    async def go(u: Update) -> None:
        await dp.feed_update(bot, u)

    # Сводка
    await go(upd_msg(ADMIN, "/admin"))
    t = last_text()
    check("/admin: сводка с выручкой, LZT и резервом", "Выручка" in t and "LZT" in t and "Резерв" in t)
    check("в сводке 7 дней и всё время", "7 дней" in t and "Всего" in t)
    check("кнопки разделов", {"ap:u:all:0", "ap:o:all:0", "ap:b", "ap:m", "ap:s:0", "ap:p", "ap:t"} <= set(cbs()))

    # Люди: листание
    await go(upd_cb(ADMIN, "ap:u:all:0"))
    cards = [x for x in cbs() if x.startswith("ap:uc:")]
    check("список людей: 8 на странице", len(cards) == 8)
    check("есть следующая страница", "ap:u:all:1" in cbs())
    await go(upd_cb(ADMIN, "ap:u:all:1"))
    check("вторая страница: остальные 5", len([x for x in cbs() if x.startswith("ap:uc:")]) == 5)
    await go(upd_cb(ADMIN, "ap:u:bal:0"))
    check("фильтр «с балансом»: только Алиса", [x for x in cbs() if x.startswith("ap:uc:")] == ["ap:uc:1"])

    # Поиск
    await go(upd_cb(ADMIN, "ap:us"))
    await go(upd_msg(ADMIN, "@bob"))
    t = last_text()
    check("поиск по @username → карточка", "<code>2</code>" in t and "@bob" in t)
    check("имя экранировано", "Боб &lt;b&gt;" in t and "Боб <b>" not in t)
    check("карточка: друзья и пригласивший", "Пригласил" in t and "Алиса" in t)
    await go(upd_cb(ADMIN, "ap:us"))
    await go(upd_msg(ADMIN, f"#{oid}"))
    check("поиск по #заказу → покупатель", "@bob" in last_text() and "заказа" in last_text())
    await go(upd_cb(ADMIN, "ap:us"))
    await go(upd_msg(ADMIN, "+7 999 000-11-22"))
    check("поиск по номеру телефона", "@bob" in last_text())

    # Карточка
    await go(upd_cb(ADMIN, "ap:uc:1"))
    t = last_text()
    check("карточка: баланс, потратил, пополнил", "500 ₽" in t and "Потратил" in t and "66 ₽" in t)
    check("карточка: кнопки действий", {"ap:uh:1:0", "ap:ui:1:0", "ap:uo:1:0", "ap:ur:1:0", "ap:ub:1", "ap:ux:1",
                                        "ap:ut:1", "ap:um:1"} <= set(cbs()))
    await go(upd_cb(ADMIN, "ap:uh:1:0"))
    check("история баланса", "пополнение" in last_text())
    await go(upd_cb(ADMIN, "ap:ui:1:0"))
    check("пополнения", "cryptobot" in last_text() and "оплачен" in last_text())
    await go(upd_cb(ADMIN, "ap:uo:1:0"))
    oc = [x for x in cbs() if x.startswith("ap:oc:")]
    check("покупки человека", len(oc) == 1)
    await go(upd_cb(ADMIN, oc[0]))
    check("карточка заказа: номер и 2FA под спойлером", "+15550001111" in last_text() and "tg-spoiler" in last_text())
    check("из заказа — к покупателю", "ap:uc:1" in cbs())
    await go(upd_cb(ADMIN, "ap:ur:1:0"))
    check("рефералы", "ap:uc:2" in cbs() and "засчитан" in last_text())

    # Баланс
    before = (await db.get_user(1))["kop"]
    await go(upd_cb(ADMIN, "ap:ub:1"))
    await go(upd_msg(ADMIN, "+100"))
    row = await db.one("SELECT * FROM ledger WHERE user_id=1 ORDER BY id DESC LIMIT 1")
    check("начислено +100 ₽, в журнале «admin»",
          (await db.get_user(1))["kop"] == before + 10_000 and row["reason"] == "admin" and row["delta"] == 10_000)
    await go(upd_cb(ADMIN, "ap:ub:1"))
    await go(upd_msg(ADMIN, "abc"))
    check("неверная сумма — переспрашивает", "Нужна сумма" in last_text() and ADMIN in ap.WAIT)
    await go(upd_cb(ADMIN, "ap:cancel"))
    check("отмена снимает ожидание", ADMIN not in ap.WAIT)

    # Бан
    await go(upd_cb(ADMIN, "ap:ux:3"))
    await go(upd_msg(ADMIN, "спам <script>"))
    check("бан с причиной", (await db.get_user(3))["banned"] == "спам <script>")
    check("причина экранирована", "спам &lt;script&gt;" in last_text() and "ap:uxu:3" in cbs())
    await go(upd_cb(ADMIN, "ap:uxu:3"))
    check("разбан", (await db.get_user(3))["banned"] == "")

    # Доверенный
    await go(upd_cb(ADMIN, "ap:ut:1"))
    check("доверенный включён", (await db.get_user(1))["trusted"] == 1 and "Доверенный" in last_text())
    await go(upd_cb(ADMIN, "ap:u:tr:0"))
    check("фильтр «доверенные»", [x for x in cbs() if x.startswith("ap:uc:")] == ["ap:uc:1"])
    await go(upd_cb(ADMIN, "ap:ut:1"))
    check("доверенный выключен", (await db.get_user(1))["trusted"] == 0)

    # Написать
    i = len(CALLS)
    await go(upd_cb(ADMIN, "ap:um:2"))
    await go(upd_msg(ADMIN, "Привет от админа"))
    check("написать: копия ушла человеку",
          any(type(m).__name__ == "CopyMessage" and m.chat_id == 2 for m in CALLS[i:]))

    # Заказы
    await go(upd_cb(ADMIN, "ap:o:all:0"))
    check("список заказов", f"ap:oc:{oid}" in cbs())
    await go(upd_cb(ADMIN, "ap:o:done:0"))
    check("фильтр заказов", f"ap:oc:{oid}" in cbs())
    await go(upd_cb(ADMIN, "ap:os"))
    await go(upd_msg(ADMIN, f"#{oid}"))
    check("поиск заказа по #id", f"Заказ #{oid}" in last_text())
    await go(upd_cb(ADMIN, "ap:os"))
    await go(upd_msg(ADMIN, "+79990001122"))
    check("поиск заказа по номеру", f"Заказ #{oid}" in last_text())

    # Настройки
    await go(upd_cb(ADMIN, "ap:s:0"))
    check("настройки: список", "MARKUP" in last_text())
    idx = list(config.EDITABLE).index("MARKUP")
    await go(upd_cb(ADMIN, f"ap:se:{idx}"))
    await go(upd_msg(ADMIN, "0.15"))
    check("MARKUP = 0.15 применён", config.MARKUP == 0.15)
    check("MARKUP сохранён в базе", await db.get_setting("cfg:MARKUP") == "0.15")
    await go(upd_cb(ADMIN, f"ap:se:{idx}"))
    await go(upd_msg(ADMIN, "-1"))
    check("отрицательная наценка не принята", config.MARKUP == 0.15)
    await go(upd_cb(ADMIN, "ap:cancel"))
    gi = list(config.EDITABLE).index("GIVEAWAY_ON")
    was = config.GIVEAWAY_ON
    await go(upd_cb(ADMIN, f"ap:se:{gi}"))
    check("переключатель меняется нажатием", config.GIVEAWAY_ON == (not was))
    if "MAX_PER_DAY" in config.EDITABLE:
        mi = list(config.EDITABLE).index("MAX_PER_DAY")
        await go(upd_cb(ADMIN, f"ap:se:{mi}"))
        await go(upd_msg(ADMIN, "0"))
        check("лимит 0 → «без лимита»", "без лимита" in last_text())

    # Промокоды и скидки
    await go(upd_cb(ADMIN, "ap:pn"))
    await go(upd_msg(ADMIN, "sale 50 100"))
    r = await db.one("SELECT rowid rid, * FROM promocodes WHERE code='SALE'")
    check("промокод создан", r is not None and r["kop"] == 5000 and r["uses_left"] == 100)
    await go(upd_cb(ADMIN, f"ap:pd:{r['rid']}"))
    await go(upd_cb(ADMIN, f"ap:pdy:{r['rid']}"))
    check("промокод удалён", await db.one("SELECT 1 FROM promocodes WHERE code='SALE'") is None)
    await go(upd_cb(ADMIN, "ap:pkn"))
    await go(upd_msg(ADMIN, "rus 5"))
    check("скидка на страну", (await db.promos()).get("RUS") == 5)
    await go(upd_cb(ADMIN, "ap:pkd:RUS"))
    check("скидка снята", "RUS" not in await db.promos())

    # Главное меню
    await go(upd_cb(ADMIN, "ap:m"))
    await go(upd_cb(ADMIN, "ap:mt"))
    await go(upd_msg(ADMIN, "Привет мир", [MessageEntity(type="bold", offset=0, length=6)]))
    check("текст меню сохранён как HTML", await db.get_setting("menu_text") == "<b>Привет</b> мир")
    await go(upd_cb(ADMIN, "ap:ms:primary"))
    check("стиль кнопки маркета", await db.get_setting("menu_button_style") == "primary")
    await go(upd_cb(ADMIN, "ap:mr:all"))
    check("сброс меню", await db.get_setting("menu_text") == "" and await db.get_setting("menu_button_style") == "")

    # Рассылка
    await go(upd_cb(ADMIN, "ap:b"))
    check("рассылка ждёт сообщение", ap.WAIT.get(ADMIN, {}).get("kind") == "bc")
    await go(upd_msg(ADMIN, "Скидки сегодня"))
    check("черновик и предпросмотр", ADMIN in ap.DRAFT and any(
        type(m).__name__ == "CopyMessage" and m.chat_id == ADMIN for m in CALLS))
    await go(upd_cb(ADMIN, "ap:bb"))
    await go(upd_msg(ADMIN, "Купить | https://t.me/x #blue"))
    btn = ap.DRAFT[ADMIN]["kb"].inline_keyboard[0][0]
    check("кнопка разобрана: текст, ссылка, стиль", btn.text == "Купить" and btn.url == "https://t.me/x"
          and btn.style == "primary")
    await go(upd_cb(ADMIN, "ap:bs:all"))
    check("подтверждение: 3 человека", "<b>3</b>" in last_text())
    i = len(CALLS)
    await go(upd_cb(ADMIN, "ap:bsy:all"))
    await asyncio.wait_for(ap.BC_TASK, 10)
    copies = [m for m in CALLS[i:] if type(m).__name__ == "CopyMessage" and m.chat_id in (1, 2, 3)]
    check("разослано 3 людям", len(copies) == 3 and ap.BC["sent"] == 3)
    check("у кнопки style=primary",
          all(m.reply_markup and m.reply_markup.inline_keyboard[0][0].style == "primary" for m in copies))
    check("заблокировавшим не слали", not any(type(m).__name__ == "CopyMessage" and m.chat_id >= 100
                                              and m.chat_id != ADMIN for m in CALLS[i:]))
    check("итоговый отчёт", "закончена" in texts_since(i))

    rows, errs = ap.parse_buttons("A | https://a.ru ;; B | https://b.ru #green\nплохо", None)
    check("разбор: два в ряд, ошибка на плохой строке",
          len(rows) == 1 and len(rows[0]) == 2 and rows[0][1].style == "success" and len(errs) == 1)
    txt = "\U0001F525 Огонь | https://f.ru"
    rows, errs = ap.parse_buttons(txt, [MessageEntity(type="custom_emoji", offset=0, length=2,
                                                      custom_emoji_id="555")])
    check("премиум-эмодзи в начале → иконка кнопки",
          not errs and rows[0][0].icon_custom_emoji_id == "555" and rows[0][0].text == "Огонь")

    # Инструменты
    await go(upd_cb(ADMIN, "ap:tl"))
    check("баланс LZT", "Баланс LZT" in last_text())
    i = len(CALLS)
    await go(upd_cb(ADMIN, "ap:tc"))
    doc = [m for m in CALLS[i:] if type(m).__name__ == "SendDocument"]
    check("выгрузка CSV", bool(doc) and b"alice" in doc[0].document.data)

    # Подделки и чужие
    i = len(CALLS)
    for bad in ("ap:uc:abc", "ap:se:999", "ap:u:zzz:-5", "ap:oc:", "ap:pkd:rus", "ap:zz", "ap:uc:1:" + "9" * 70,
                "ap:ms:evil", "ap:bsy:nope"):
        await go(upd_cb(ADMIN, bad))
    errs_ = [m for m in CALLS[i:] if isinstance(m, AnswerCallbackQuery) and (m.text or "").startswith("Ошибка")]
    check("подделанные callback не роняют панель", not errs_)
    i = len(CALLS)
    await go(upd_cb(1, "ap:home"))
    await go(upd_cb(1, "ap:ub:1"))
    await go(upd_msg(1, "/admin"))
    check("не-админ ничего не получает", len(CALLS) == i and 1 not in ap.WAIT)
    await go(upd_cb(ADMIN, "ap:us"))
    i = len(CALLS)
    await go(upd_msg(1, "@bob"))
    check("ожидание админа не ловит сообщения людей", len(CALLS) == i and ADMIN in ap.WAIT)
    ap.WAIT[ADMIN]["ts"] -= 700
    await go(upd_msg(ADMIN, "@bob"))
    check("ожидание истекает через 10 минут", len(CALLS) == i and ADMIN not in ap.WAIT)

    lens = [len((b.callback_data or "").encode()) for m in CALLS
            for b in sum((getattr(getattr(m, "reply_markup", None), "inline_keyboard", None) or []), [])]
    check("callback_data ≤ 64 байт", max(lens) <= 64)

    await db.close()
    await bot.session.close()
    print()
    print("АДМИН-ПАНЕЛЬ: ВСЁ В ПОРЯДКЕ" if not FAILS else f"ОШИБКИ: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
