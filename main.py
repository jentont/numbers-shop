"""Точка входа: база, бот, Mini App и фоновые задачи в одном процессе.

    python main.py

Без BOT_TOKEN запускается только витрина (для проверки: DEV_AUTH=1,
http://localhost:8090/?dev=1).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from aiohttp import web

import config
import crypto
import db
import lzt
import shop
import web as webmod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("numbers")


async def worker() -> None:
    """Оплаты, резерв и конкурс. Воркер не имеет права умирать."""
    last_reserve = 0.0
    while True:
        try:
            await crypto.poll()
            loop = asyncio.get_running_loop()
            if loop.time() - last_reserve > 300:
                last_reserve = loop.time()
                await shop.keep_reserve()
            now = dt.datetime.now(shop.MSK)
            if config.GIVEAWAY_ON and now.hour == config.GIVEAWAY_HOUR:
                row = await db.one("SELECT status FROM giveaways WHERE day=?", (shop.today(),))
                if row is None or row["status"] == "open":
                    res = await shop.draw()
                    if res.get("status") == "done" and config.GIVEAWAY_BROADCAST and shop.bot:
                        import bot as botmod
                        u = await db.get_user(res["winner"])
                        await botmod.broadcast("gw_res", name=shop._mask(u["name"] if u else ""))  # noqa: SLF001
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("воркер: %s", exc)
        await asyncio.sleep(config.POLL_INTERVAL)


async def run_bot():
    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

    import bot as botmod
    import emoji

    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML", link_preview_is_disabled=True))
    me = await bot.get_me()
    config.BOT_USERNAME = me.username
    shop.bot = bot
    await emoji.load(bot)
    if config.webapp_enabled():
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Market", web_app=WebAppInfo(url=config.WEBAPP_URL)))
        except Exception as exc:  # noqa: BLE001
            log.warning("кнопка меню: %s", exc)
    await bot.set_my_commands([BotCommand(command="start", description="Menu")])
    dp = Dispatcher()
    import adminpanel
    import textmode
    dp.include_router(adminpanel.router)  # первым: /admin и ap:*
    dp.include_router(botmod.router)
    dp.include_router(textmode.router)  # после команд: ловит свободный текст
    log.info("бот @%s запущен", me.username)
    return bot, dp


async def main() -> None:
    await db.init()
    runner = web.AppRunner(webmod.app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
    log.info("витрина: http://localhost:%s%s", config.PORT, " (DEV: ?dev=1)" if config.DEV_AUTH else "")
    if config.LZT_DEMO:
        log.warning("LZT в демо-режиме: лоты выдуманы, покупки без денег")
    tasks = [asyncio.create_task(shop.snapshot_worker()), asyncio.create_task(worker())]
    try:
        if config.BOT_TOKEN:
            bot, dp = await run_bot()
            await dp.start_polling(bot, handle_signals=False)
        else:
            log.warning("BOT_TOKEN не задан — работает только витрина")
            await asyncio.Event().wait()
    finally:
        for t in tasks:
            t.cancel()
        await lzt.close()
        await crypto.close()
        await runner.cleanup()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
