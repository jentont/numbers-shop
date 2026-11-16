"""Настройки Solutions Numbers. Всё берётся из .env рядом с этим файлом.

Деньги внутри — рубли в копейках (int), чтобы не ловить ошибки float.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _s(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _i(key: str, default: int) -> int:
    try:
        return int(_s(key, str(default)))
    except ValueError:
        return default


def _f(key: str, default: float) -> float:
    try:
        return float(_s(key, str(default)).replace(",", "."))
    except ValueError:
        return default


def _b(key: str, default: bool = False) -> bool:
    return _s(key, "1" if default else "0").lower() in ("1", "true", "yes", "on")


# ── Telegram ──────────────────────────────────────────────────────────
BOT_TOKEN = _s("BOT_TOKEN")
BOT_USERNAME = _s("BOT_USERNAME").lstrip("@")          # заполняется само при старте
ADMIN_IDS = {int(x) for x in _s("ADMIN_IDS").replace(" ", "").split(",") if x.lstrip("-").isdigit()}
WEBAPP_URL = _s("WEBAPP_URL").rstrip("/")              # https-адрес, где открыт этот сервер
PORT = _i("PORT", 8090)
SUPPORT = _s("SUPPORT")                                # @ник поддержки
CHANNEL = _s("CHANNEL")                                # @канал для конкурса (бот — админ канала)
CHANNEL_URL = _s("CHANNEL_URL") or (f"https://t.me/{CHANNEL.lstrip('@')}" if CHANNEL.startswith("@") else "")
BRAND = _s("BRAND", "Solutions Numbers")

#: Вход в витрину без Telegram: http://localhost:8090/?dev=<id>. Только для проверки.
DEV_AUTH = _b("DEV_AUTH", False)

DB_PATH = Path(_s("DB_PATH", str(BASE_DIR / "data" / "shop.db")))
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH

# ── LZT Market ────────────────────────────────────────────────────────
LZT_TOKEN = _s("LZT_TOKEN")
LZT_BASE = _s("LZT_BASE", "https://api.lzt.market").rstrip("/")
#: Без токена или с LZT_DEMO=1 маркет работает на выдуманных лотах и
#: ничего не покупает — чтобы посмотреть витрину и прогнать сценарии.
LZT_DEMO = _b("LZT_DEMO", not LZT_TOKEN)
#: Какие лоты вообще показываем: только без спамблока и только с этих
#: способов происхождения (autoreg — авторег, самый дешёвый и массовый).
LZT_ORIGINS = [x for x in _s("LZT_ORIGINS", "autoreg,self_registration,personal,resale").split(",") if x]
LZT_NO_SPAM = _b("LZT_NO_SPAM", True)
LZT_MAX_PRICE = _f("LZT_MAX_PRICE", 3000)
#: Продавцы: у новичков и тех, кто «восстанавливает» проданные аккаунты, не покупаем.
SELLER_MIN_SOLD = _i("SELLER_MIN_SOLD", 50)            # минимум продаж у продавца
SELLER_MAX_RESTORE = _i("SELLER_MAX_RESTORE", 10)      # не больше % восстановленных аккаунтов
#: Чёрный список продавцов: ник или ID через запятую (регистр не важен).
SELLER_BLACKLIST = _s("SELLER_BLACKLIST", "AccPoint")
#: Столько подтверждённых «не работает» по аккаунтам продавца — и он в чёрном списке сам.
SELLER_STRIKES = _i("SELLER_STRIKES", 3)              # дороже — не продаём вовсе
CACHE_TTL = _i("CACHE_TTL", 90)
#: Общий обход каталога за цикл: дешёвые + новые страницы (по ~40 лотов). 30 + 30 ≈ 2 400 лотов;
#: новые лоты идут вперемешку по странам — они дают разнообразие стран.
CRAWL_CHEAP_PAGES = _i("CRAWL_CHEAP_PAGES", 30)
CRAWL_NEW_PAGES = _i("CRAWL_NEW_PAGES", 30)
CRAWL_EVERY = _i("CRAWL_EVERY", 180)                   # секунд между обходами                        # секунд держим выдачу LZT

# ── Цены ──────────────────────────────────────────────────────────────
MARKUP = _f("MARKUP", 0.10)                            # +10 % к цене LZT
MIN_MARGIN_RUB = _f("MIN_MARGIN_RUB", 2)               # но не меньше 2 ₽ с аккаунта
STAR_RUB = _f("STAR_RUB", 1.4)                         # номинал звезды в рублях
STARS_MARKUP = _f("STARS_MARKUP", 2.0)                 # в звёздах ×2 (+100 %)

# ── Резерв (мгновенная выдача) ────────────────────────────────────────
RESERVE_SIZE = _i("RESERVE_SIZE", 10)
RESERVE_COUNTRIES = [x for x in _s("RESERVE_COUNTRIES", "RUS").split(",") if x]
RESERVE_MAX_PRICE = _f("RESERVE_MAX_PRICE", 40)        # ₽ за аккаунт в резерв, не дороже
RESERVE_MAX_AGE_H = _i("RESERVE_MAX_AGE_H", 20)        # старше — в приз конкурса, пока жива гарантия

# ── Конкурс ───────────────────────────────────────────────────────────
GIVEAWAY_ON = _b("GIVEAWAY_ON", True)
GIVEAWAY_HOUR = _i("GIVEAWAY_HOUR", 20)                # час розыгрыша по МСК
GIVEAWAY_MAX_PRICE = _f("GIVEAWAY_MAX_PRICE", 15)      # приз — аккаунт не дороже 15 ₽
GIVEAWAY_BROADCAST = _b("GIVEAWAY_BROADCAST", True)    # рассылка анонса и итогов

# ── Рефералы ──────────────────────────────────────────────────────────
REF_GOAL = _i("REF_GOAL", 15)                          # друзей за один аккаунт
REF_PRIZE_MAX = _f("REF_PRIZE_MAX", 15)                # приз — аккаунт не дороже 15 ₽
REF_DAILY_MAX = _i("REF_DAILY_MAX", 20)                # не больше 20 призов в сутки на всех

# ── Защита от злоупотреблений ─────────────────────────────────────────
#: Лимит покупок в сутки. 0 — без лимита (по умолчанию: на маркете лимитов нет,
#: а лимит у нас — потерянные продажи). Можно включить из админки, если пойдёт спам.
MAX_PER_DAY = _i("MAX_PER_DAY", 0)
MAX_PER_DAY_NEW = _i("MAX_PER_DAY_NEW", 0)             # для тех, кто пришёл меньше суток назад

# ── Гарантия ──────────────────────────────────────────────────────────
GUARANTEE_H = _i("GUARANTEE_H", 24)                    # столько часов можно сообщить «не работает»
RESERVE_CHECK_MIN = _i("RESERVE_CHECK_MIN", 30)        # как часто перепроверять резерв

# ── Оплата ────────────────────────────────────────────────────────────
CRYPTOBOT_TOKEN = _s("CRYPTOBOT_TOKEN")                 # @send (CryptoBot) → Crypto Pay
CRYPTOBOT_TESTNET = _b("CRYPTOBOT_TESTNET")
CRYPTOBOT_ASSET = _s("CRYPTOBOT_ASSET", "USDT")
XROCKET_TOKEN = _s("XROCKET_TOKEN")
XROCKET_TESTNET = _b("XROCKET_TESTNET")
XROCKET_ASSET = _s("XROCKET_ASSET", "USDT")
TON_WALLET = _s("TON_WALLET")                          # адрес Tonkeeper для прямых переводов
TONCENTER_URL = _s("TONCENTER_URL", "https://toncenter.com/api/v3")
TONCENTER_KEY = _s("TONCENTER_KEY")
TONAPI_URL = _s("TONAPI_URL", "https://tonapi.io")
USDT_RUB = _f("USDT_RUB", 95)                          # резервные курсы, если API молчат
TON_RUB = _f("TON_RUB", 300)
STARS_ON = _b("STARS_ON", True)
TOPUP_MIN = _f("TOPUP_MIN", 30)
INVOICE_TTL_MIN = _i("INVOICE_TTL_MIN", 30)
PAY_TOLERANCE = _f("PAY_TOLERANCE", 0.98)
POLL_INTERVAL = _i("POLL_INTERVAL", 30)


def crypto_providers() -> list[str]:
    out = []
    if CRYPTOBOT_TOKEN:
        out.append("cryptobot")
    if XROCKET_TOKEN:
        out.append("xrocket")
    if TON_WALLET:
        out.append("ton")
    return out


def webapp_enabled() -> bool:
    return WEBAPP_URL.startswith("https://")


# ── Настройки из админки ──────────────────────────────────────────────
#: Что можно менять из /admin без правки кода. Значения хранятся в
#: таблице settings под ключом "cfg:<ИМЯ>" и поверх .env применяются
#: при старте и сразу после изменения (apply_overrides).
EDITABLE: dict[str, type] = {
    "MARKUP": float, "MIN_MARGIN_RUB": float, "STARS_MARKUP": float, "STAR_RUB": float,
    "RESERVE_SIZE": int, "RESERVE_MAX_PRICE": float, "RESERVE_COUNTRIES": list,
    "GIVEAWAY_ON": bool, "GIVEAWAY_HOUR": int, "GIVEAWAY_MAX_PRICE": float, "GIVEAWAY_BROADCAST": bool,
    "REF_GOAL": int, "REF_PRIZE_MAX": float, "REF_DAILY_MAX": int,
    "MAX_PER_DAY": int, "MAX_PER_DAY_NEW": int, "GUARANTEE_H": int,
    "TOPUP_MIN": float, "LZT_MAX_PRICE": float,
    "SELLER_MIN_SOLD": int, "SELLER_MAX_RESTORE": int, "SELLER_BLACKLIST": str, "SELLER_STRIKES": int,
    "CHANNEL": str, "CHANNEL_URL": str, "SUPPORT": str, "SUB_REQUIRED": bool,
}

#: Обязательная подписка на CHANNEL, чтобы пользоваться ботом и Mini App.
SUB_REQUIRED = _b("SUB_REQUIRED", True)


def _cast(name: str, raw: str):
    kind = EDITABLE[name]
    if kind is bool:
        return raw.strip().lower() in ("1", "true", "yes", "on", "да", "вкл")
    if kind is list:
        return [x.strip().upper() for x in raw.split(",") if x.strip()]
    return kind(raw.strip().replace(",", ".")) if kind in (int, float) else raw.strip()


def apply_overrides(values: dict[str, str]) -> list[str]:
    """Применяет настройки {"MARKUP": "0.12", ...}. Возвращает имена, которые не подошли."""
    bad = []
    g = globals()
    for name, raw in values.items():
        if name not in EDITABLE:
            bad.append(name)
            continue
        try:
            g[name] = _cast(name, raw)
        except (TypeError, ValueError):
            bad.append(name)
    if "CHANNEL" in values and "CHANNEL_URL" not in values:
        ch = g["CHANNEL"]
        g["CHANNEL_URL"] = f"https://t.me/{ch.lstrip('@')}" if ch.startswith("@") else g["CHANNEL_URL"]
    return bad
