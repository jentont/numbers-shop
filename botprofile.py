"""Профиль бота: название, короткое описание, описание и команды на 6 языках.

Бот выставляет их сам при запуске (setMyName / setMyShortDescription /
setMyDescription / setMyCommands) — и только если текст изменился, потому
что Telegram ограничивает частоту этих вызовов.

В описаниях нет эмодзи: премиум-эмодзи Telegram там не поддерживает,
а обычные в этом боте запрещены.

Картинки для BotFather лежат в assets/brand/ (см. BOTFATHER.md):
avatar_1024.png — аватарка, description_640x360.jpg — картинка над
описанием, miniapp_640x360.jpg — превью Mini App.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat

import config

log = logging.getLogger("numbers.profile")

NAME = "Solutions Numbers"

#: Короткое описание — видно в профиле бота и при пересылке ссылки (до 120 символов).
SHORT = {
    "ru": "Telegram-аккаунты 50+ стран. Мгновенная выдача, цены на 10% выше маркета, гарантия 24 часа.",
    "en": "Telegram accounts from 50+ countries. Instant delivery, 10% above market price, 24h guarantee.",
    "es": "Cuentas de Telegram de 50+ países. Entrega al instante, 10% sobre el mercado, garantía 24 h.",
    "ar": "حسابات تيليجرام من أكثر من 50 دولة. تسليم فوري، أعلى من السوق بـ10% فقط، ضمان 24 ساعة.",
    "hi": "50+ देशों के Telegram अकाउंट। तुरंत डिलीवरी, बाज़ार से सिर्फ़ 10% ज़्यादा, 24 घंटे की गारंटी।",
    "zh": "50 多个国家的 Telegram 账号。即时发货，仅比市场价高 10%，24 小时保障。",
}

#: Описание — экран «Что умеет этот бот?» до нажатия «Старт» (до 512 символов).
LONG = {
    "ru": (
        "Solutions Numbers — маркет Telegram-аккаунтов 50+ стран.\n\n"
        "— Россия +7, СНГ, Европа, Азия, Америка: фильтры и сортировка по цене\n"
        "— Мгновенная выдача: номер ваш сразу после оплаты\n"
        "— Код входа приходит прямо в приложение\n"
        "— Каждый аккаунт проверен, гарантия 24 часа\n"
        "— Оплата: CryptoBot, xRocket, Tonkeeper, Telegram Stars\n"
        "— Конкурс каждый день и аккаунт бесплатно за друзей\n\n"
        "Нажмите «Старт», чтобы открыть маркет."
    ),
    "en": (
        "Solutions Numbers is a marketplace of Telegram accounts from 50+ countries.\n\n"
        "— Russia +7, CIS, Europe, Asia, Americas: filters and price sorting\n"
        "— Instant delivery: the number is yours right after payment\n"
        "— The login code arrives right in the app\n"
        "— Every account is checked, 24-hour guarantee\n"
        "— Pay with CryptoBot, xRocket, Tonkeeper or Telegram Stars\n"
        "— Daily giveaway and a free account for inviting friends\n\n"
        "Tap Start to open the market."
    ),
    "es": (
        "Solutions Numbers: mercado de cuentas de Telegram de más de 50 países.\n\n"
        "— Rusia +7, CEI, Europa, Asia, América: filtros y orden por precio\n"
        "— Entrega instantánea: el número es tuyo nada más pagar\n"
        "— El código de acceso llega directamente a la app\n"
        "— Cada cuenta verificada, garantía de 24 horas\n"
        "— Pago con CryptoBot, xRocket, Tonkeeper o Telegram Stars\n"
        "— Sorteo diario y cuenta gratis por invitar amigos\n\n"
        "Pulsa «Iniciar» para abrir el mercado."
    ),
    "ar": (
        "Solutions Numbers — متجر حسابات تيليجرام من أكثر من 50 دولة.\n\n"
        "— روسيا +7، رابطة الدول، أوروبا، آسيا، الأمريكتان: فلاتر وترتيب حسب السعر\n"
        "— تسليم فوري: الرقم لك فور الدفع\n"
        "— رمز الدخول يصل مباشرة إلى التطبيق\n"
        "— كل حساب مُفحوص، ضمان 24 ساعة\n"
        "— الدفع عبر CryptoBot أو xRocket أو Tonkeeper أو نجوم تيليجرام\n"
        "— سحب يومي وحساب مجاني مقابل دعوة الأصدقاء\n\n"
        "اضغط «ابدأ» لفتح المتجر."
    ),
    "hi": (
        "Solutions Numbers — 50+ देशों के Telegram अकाउंट का मार्केट।\n\n"
        "— रूस +7, CIS, यूरोप, एशिया, अमेरिका: फ़िल्टर और कीमत से सॉर्ट\n"
        "— तुरंत डिलीवरी: भुगतान के तुरंत बाद नंबर आपका\n"
        "— लॉगिन कोड सीधे ऐप में आता है\n"
        "— हर अकाउंट जाँचा हुआ, 24 घंटे की गारंटी\n"
        "— भुगतान: CryptoBot, xRocket, Tonkeeper या Telegram Stars\n"
        "— रोज़ गिवअवे और दोस्तों को बुलाने पर मुफ़्त अकाउंट\n\n"
        "मार्केट खोलने के लिए «Start» दबाएँ।"
    ),
    "zh": (
        "Solutions Numbers——50 多个国家的 Telegram 账号商城。\n\n"
        "— 俄罗斯 +7、独联体、欧洲、亚洲、美洲：支持筛选和按价格排序\n"
        "— 即时发货：付款后号码立即归你\n"
        "— 登录验证码直接显示在应用内\n"
        "— 每个账号都经过检测，24 小时保障\n"
        "— 支持 CryptoBot、xRocket、Tonkeeper 和 Telegram Stars 付款\n"
        "— 每日抽奖，邀请好友免费得账号\n\n"
        "点击「开始」打开商城。"
    ),
}

#: Команды в меню «/» для всех.
COMMANDS = {
    "ru": [("start", "Главное меню"), ("terms", "Условия использования"), ("privacy", "Политика конфиденциальности")],
    "en": [("start", "Main menu"), ("terms", "Terms of Use"), ("privacy", "Privacy Policy")],
    "es": [("start", "Menú principal"), ("terms", "Términos de uso"), ("privacy", "Política de privacidad")],
    "ar": [("start", "القائمة الرئيسية"), ("terms", "شروط الاستخدام"), ("privacy", "سياسة الخصوصية")],
    "hi": [("start", "मुख्य मेनू"), ("terms", "उपयोग की शर्तें"), ("privacy", "गोपनीयता नीति")],
    "zh": [("start", "主菜单"), ("terms", "使用条款"), ("privacy", "隐私政策")],
}
#: Дополнительно у админов в меню «/».
ADMIN_COMMANDS = [("admin", "Админ-панель"), ("emoji_list", "Премиум-эмодзи: что найдено")]


def _check() -> None:
    for lang, s in SHORT.items():
        assert len(s) <= 120, f"short {lang}: {len(s)}"
    for lang, s in LONG.items():
        assert len(s) <= 512, f"long {lang}: {len(s)}"


_check()


async def apply(bot: Bot) -> None:
    """Выставляет профиль бота. Ошибки не роняют запуск — только пишутся в лог."""
    for lang in [None, *SHORT]:
        key = lang or "en"            # без языка — английский, для всех остальных языков мира
        code = lang or ""
        try:
            if (await bot.get_my_short_description(language_code=code)).short_description != SHORT[key]:
                await bot.set_my_short_description(short_description=SHORT[key], language_code=code)
            if (await bot.get_my_description(language_code=code)).description != LONG[key]:
                await bot.set_my_description(description=LONG[key], language_code=code)
            await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMMANDS[key]],
                                      language_code=code or None)
        except TelegramAPIError as exc:
            log.warning("профиль бота (%s): %s", key, exc)
    try:
        if (await bot.get_my_name()).name != NAME:
            await bot.set_my_name(name=NAME)
    except TelegramAPIError as exc:
        log.warning("имя бота: %s", exc)
    admin_cmds = [BotCommand(command=c, description=d) for c, d in COMMANDS["ru"] + ADMIN_COMMANDS]
    for aid in config.ADMIN_IDS:
        try:
            await bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=aid))
        except TelegramAPIError as exc:
            log.debug("команды админа %s: %s", aid, exc)
