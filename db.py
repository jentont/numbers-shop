"""База на SQLite. Одно соединение на процесс, все деньги — в копейках.

Каждое списание и зачисление — одним UPDATE с условием, поэтому два
одновременных нажатия «Купить» не уведут баланс в минус, а повторная
проверка счёта не зачислит его дважды.
"""
from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL DEFAULT '',
    username   TEXT    NOT NULL DEFAULT '',
    lang       TEXT    NOT NULL DEFAULT '',
    kop        INTEGER NOT NULL DEFAULT 0,
    tour_done  INTEGER NOT NULL DEFAULT 0,
    blocked    INTEGER NOT NULL DEFAULT 0,   -- заблокировал бота: не шлём рассылки
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    delta      INTEGER NOT NULL,
    reason     TEXT    NOT NULL,             -- topup | buy | refund | admin
    ref        TEXT    NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id, id);
CREATE TABLE IF NOT EXISTS invoices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    provider    TEXT    NOT NULL,            -- cryptobot | xrocket | ton | stars
    external_id TEXT,
    asset       TEXT    NOT NULL DEFAULT '',
    amount      REAL    NOT NULL DEFAULT 0,  -- в валюте провайдера
    kop         INTEGER NOT NULL DEFAULT 0,  -- сколько зачислим
    rate        REAL    NOT NULL DEFAULT 0,
    comment     TEXT    NOT NULL DEFAULT '',
    pay_url     TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'new',  -- new | paid | expired
    created_at  INTEGER NOT NULL,
    paid_at     INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_ext
    ON invoices(provider, external_id) WHERE external_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    source      TEXT    NOT NULL,            -- live | reserve | giveaway
    item_id     INTEGER NOT NULL,            -- id лота на LZT
    country     TEXT    NOT NULL DEFAULT '',
    cost_kop    INTEGER NOT NULL DEFAULT 0,  -- заплатили LZT
    price_kop   INTEGER NOT NULL DEFAULT 0,  -- заплатил покупатель
    status      TEXT    NOT NULL DEFAULT 'pending',  -- pending | done | refunded
    phone       TEXT    NOT NULL DEFAULT '',
    password    TEXT    NOT NULL DEFAULT '',
    info        TEXT    NOT NULL DEFAULT '{}',
    error       TEXT    NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL,
    done_at     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, id);
CREATE TABLE IF NOT EXISTS reserve (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL UNIQUE,
    country     TEXT    NOT NULL,
    cost_kop    INTEGER NOT NULL,
    phone       TEXT    NOT NULL DEFAULT '',
    password    TEXT    NOT NULL DEFAULT '',
    info        TEXT    NOT NULL DEFAULT '{}',
    status      TEXT    NOT NULL DEFAULT 'ready',   -- ready | sold | prize | dead
    bought_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS giveaways (
    day         TEXT PRIMARY KEY,            -- 2026-11-15 по МСК
    status      TEXT NOT NULL DEFAULT 'open',    -- open | done | skipped
    winner_id   INTEGER,
    order_id    INTEGER,
    note        TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS giveaway_entries (
    day     TEXT    NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (day, user_id)
);
CREATE TABLE IF NOT EXISTS promos (
    country TEXT PRIMARY KEY,                -- ISO-3, например RUS
    percent INTEGER NOT NULL                 -- скидка с нашей цены
);
CREATE TABLE IF NOT EXISTS promocodes (
    code       TEXT PRIMARY KEY,             -- в верхнем регистре
    kop        INTEGER NOT NULL,             -- сколько начисляет
    uses_left  INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS promo_uses (
    code    TEXT    NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (code, user_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_conn: aiosqlite.Connection | None = None


def conn() -> aiosqlite.Connection:
    assert _conn is not None, "db.init() не вызван"
    return _conn


def now() -> int:
    return int(time.time())


async def init(path=None) -> None:
    global _conn
    path = path or config.DB_PATH
    if str(path) != ":memory:":
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _conn = await aiosqlite.connect(path, isolation_level=None)
    _conn.row_factory = aiosqlite.Row
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA busy_timeout=5000")
    await _conn.executescript(SCHEMA)
    await _migrate()
    await load_overrides()        # настройки из /admin переживают перезапуск


async def _migrate() -> None:
    """Миграции для старых баз: новые колонки добавляются, если их нет."""
    # Миграции для старых баз: новые колонки добавляются, если их нет.
    cols = {r[1] for r in await (await _conn.execute("PRAGMA table_info(users)")).fetchall()}
    if "ref_by" not in cols:
        await _conn.execute("ALTER TABLE users ADD COLUMN ref_by INTEGER")
    if "terms_at" not in cols:
        await _conn.execute("ALTER TABLE users ADD COLUMN terms_at INTEGER NOT NULL DEFAULT 0")
    if "trusted" not in cols:
        await _conn.execute("ALTER TABLE users ADD COLUMN trusted INTEGER NOT NULL DEFAULT 0")
    if "banned" not in cols:
        await _conn.execute("ALTER TABLE users ADD COLUMN banned TEXT NOT NULL DEFAULT ''")
    if "ref_ok" not in cols:
        await _conn.execute("ALTER TABLE users ADD COLUMN ref_ok INTEGER NOT NULL DEFAULT 0")
    if "ref_used" not in cols:
        await _conn.execute("ALTER TABLE users ADD COLUMN ref_used INTEGER NOT NULL DEFAULT 0")
    rcols = {r[1] for r in await (await _conn.execute("PRAGMA table_info(reserve)")).fetchall()}
    if "checked_at" not in rcols:
        await _conn.execute("ALTER TABLE reserve ADD COLUMN checked_at INTEGER NOT NULL DEFAULT 0")
    ocols = {r[1] for r in await (await _conn.execute("PRAGMA table_info(orders)")).fetchall()}
    if "reported" not in ocols:
        await _conn.execute("ALTER TABLE orders ADD COLUMN reported INTEGER NOT NULL DEFAULT 0")


# ── Резервные копии ───────────────────────────────────────────────────

async def backup_file(dest) -> None:
    """Целая копия базы одним файлом (без WAL): VACUUM INTO не мешает работе бота."""
    from pathlib import Path
    dest = Path(dest)
    dest.unlink(missing_ok=True)
    await run("VACUUM INTO ?", (str(dest),))


def check_backup(src) -> dict:
    """Проверяет файл перед восстановлением: это наша база и она целая."""
    import sqlite3
    try:
        c = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        try:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("файл повреждён")
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"users", "orders", "ledger", "settings"} <= tables:
                raise ValueError("это не база Solutions Numbers")
            users = c.execute("SELECT COUNT(*), COALESCE(SUM(kop),0) FROM users").fetchone()
            orders = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        finally:
            c.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"не база SQLite: {exc}") from exc
    return {"users": users[0], "kop": users[1], "orders": orders}


async def restore_from(src) -> dict:
    """Заменяет текущую базу копией из файла — на лету, без перезапуска бота."""
    info = check_backup(src)
    async with aiosqlite.connect(src) as s:
        await s.backup(conn())
    await _migrate()
    await load_overrides()
    return info


async def stats_brief() -> dict:
    u = await one("SELECT COUNT(*) n, COALESCE(SUM(kop),0) k FROM users")
    o = await one("SELECT COUNT(*) n FROM orders")
    return {"users": u["n"], "kop": u["k"], "orders": o["n"]}


async def close() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


async def one(sql: str, args: tuple = ()) -> aiosqlite.Row | None:
    cur = await conn().execute(sql, args)
    return await cur.fetchone()


async def all_(sql: str, args: tuple = ()) -> list[aiosqlite.Row]:
    cur = await conn().execute(sql, args)
    return list(await cur.fetchall())


async def run(sql: str, args: tuple = ()) -> aiosqlite.Cursor:
    return await conn().execute(sql, args)


# ── Настройки ─────────────────────────────────────────────────────────

async def get_setting(key: str, default: str = "") -> str:
    row = await one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


async def set_setting(key: str, value: str) -> None:
    await run("INSERT INTO settings(key,value) VALUES(?,?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# ── Люди и баланс ─────────────────────────────────────────────────────

async def touch_user(uid: int, name: str = "", username: str = "", lang: str = "") -> aiosqlite.Row:
    await run("INSERT INTO users(id,name,username,lang,created_at) VALUES(?,?,?,?,?) "
              "ON CONFLICT(id) DO UPDATE SET name=excluded.name, username=excluded.username, blocked=0",
              (uid, name[:64], username[:64], lang[:8], now()))
    return await get_user(uid)


async def get_user(uid: int) -> aiosqlite.Row | None:
    return await one("SELECT * FROM users WHERE id=?", (uid,))


async def set_lang(uid: int, lang: str) -> None:
    await run("UPDATE users SET lang=? WHERE id=?", (lang[:8], uid))


async def add_kop(uid: int, delta: int, reason: str, ref: str = "") -> int:
    """Зачисляет (или при delta<0 списывает без проверки) и пишет в журнал."""
    await run("UPDATE users SET kop=kop+? WHERE id=?", (delta, uid))
    await run("INSERT INTO ledger(user_id,delta,reason,ref,created_at) VALUES(?,?,?,?,?)",
              (uid, delta, reason, ref, now()))
    row = await get_user(uid)
    return int(row["kop"]) if row else 0


async def take_kop(uid: int, amount: int, reason: str, ref: str = "") -> bool:
    """Списывает, только если хватает. Атомарно: одно UPDATE с условием."""
    cur = await run("UPDATE users SET kop=kop-? WHERE id=? AND kop>=?", (amount, uid, amount))
    if cur.rowcount != 1:
        return False
    await run("INSERT INTO ledger(user_id,delta,reason,ref,created_at) VALUES(?,?,?,?,?)",
              (uid, -amount, reason, ref, now()))
    return True


async def history(uid: int, limit: int = 30, offset: int = 0) -> list[dict]:
    rows = await all_("SELECT delta,reason,ref,created_at FROM ledger WHERE user_id=? "
                      "ORDER BY id DESC LIMIT ? OFFSET ?", (uid, limit, offset))
    return [dict(r) for r in rows]


async def history_count(uid: int) -> int:
    row = await one("SELECT COUNT(*) n FROM ledger WHERE user_id=?", (uid,))
    return int(row["n"])


async def accept_terms(uid: int) -> None:
    await run("UPDATE users SET terms_at=? WHERE id=? AND terms_at=0", (now(), uid))


async def set_ban(uid: int, reason: str) -> bool:
    cur = await run("UPDATE users SET banned=? WHERE id=?", (reason[:200], uid))
    return cur.rowcount == 1


async def bought_today(uid: int) -> int:
    row = await one("SELECT COUNT(*) n FROM orders WHERE user_id=? AND source IN ('live','reserve') "
                    "AND status!='refunded' AND created_at>=?", (uid, now() - 86400))
    return int(row["n"])


async def whois(phone: str) -> list[aiosqlite.Row]:
    """Кому выдан номер — для разбора жалоб на спам и мошенничество."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 6:
        return []
    return await all_("SELECT o.*, u.name, u.username, u.banned FROM orders o LEFT JOIN users u ON u.id=o.user_id "
                      "WHERE replace(replace(o.phone,'+',''),' ','') LIKE ? ORDER BY o.id DESC LIMIT 10",
                      (f"%{digits[-10:]}%",))


async def find_user(ref: str) -> aiosqlite.Row | None:
    """Человек по id или @username (только те, кто уже запускал бота)."""
    ref = ref.strip().lstrip("@")
    if ref.isdigit():
        return await get_user(int(ref))
    return await one("SELECT * FROM users WHERE lower(username)=lower(?)", (ref,)) if ref else None


async def transfer(src: int, dst: int, kop: int) -> bool:
    """Перевод другу. Списание — атомарный UPDATE с условием, затем зачисление."""
    if not await take_kop(src, kop, "send", f"to {dst}"):
        return False
    await add_kop(dst, kop, "receive", f"from {src}")
    return True


async def create_promo(code: str, kop: int, uses: int) -> None:
    await run("INSERT INTO promocodes(code,kop,uses_left,created_at) VALUES(?,?,?,?) "
              "ON CONFLICT(code) DO UPDATE SET kop=excluded.kop, uses_left=excluded.uses_left",
              (code.upper(), kop, uses, now()))


async def use_promo(uid: int, code: str) -> int | str:
    """Активирует промокод. Возвращает начисленные копейки или код ошибки."""
    code = code.strip().upper()[:32]
    row = await one("SELECT * FROM promocodes WHERE code=?", (code,))
    if row is None:
        return "promo_bad"
    # Сначала «занимаем» активацию: PRIMARY KEY не даст сделать это дважды.
    cur = await run("INSERT OR IGNORE INTO promo_uses(code,user_id) VALUES(?,?)", (code, uid))
    if cur.rowcount != 1:
        return "promo_used"
    cur = await run("UPDATE promocodes SET uses_left=uses_left-1 WHERE code=? AND uses_left>0", (code,))
    if cur.rowcount != 1:
        await run("DELETE FROM promo_uses WHERE code=? AND user_id=?", (code, uid))
        return "promo_bad"
    await add_kop(uid, int(row["kop"]), "promo", code)
    return int(row["kop"])


async def set_ref(uid: int, ref_by: int) -> bool:
    """Привязывает пригласившего один раз и только новому человеку."""
    if ref_by == uid or not await get_user(ref_by):
        return False
    cur = await run("UPDATE users SET ref_by=? WHERE id=? AND ref_by IS NULL AND created_at>=?",
                    (ref_by, uid, now() - 120))
    return cur.rowcount == 1


async def referrals(uid: int) -> list[aiosqlite.Row]:
    return await all_("SELECT id FROM users WHERE ref_by=? ORDER BY created_at", (uid,))


async def use_ref_prize(uid: int, goal: int, confirmed: int) -> bool:
    """Списывает goal засчитанных друзей под приз. Атомарно."""
    cur = await run("UPDATE users SET ref_used=ref_used+? WHERE id=? AND ref_used+?<=?",
                    (goal, uid, goal, confirmed))
    return cur.rowcount == 1


# ── Счета ─────────────────────────────────────────────────────────────

async def create_invoice(uid: int, provider: str, kop: int) -> int:
    cur = await run("INSERT INTO invoices(user_id,provider,kop,created_at) VALUES(?,?,?,?)",
                    (uid, provider, kop, now()))
    return int(cur.lastrowid)


async def update_invoice(inv_id: int, **fields: Any) -> None:
    keys = ", ".join(f"{k}=?" for k in fields)
    await run(f"UPDATE invoices SET {keys} WHERE id=?", (*fields.values(), inv_id))


async def get_invoice(inv_id: int) -> aiosqlite.Row | None:
    return await one("SELECT * FROM invoices WHERE id=?", (inv_id,))


async def open_invoices() -> list[aiosqlite.Row]:
    """Открытые счета и просроченные за последние сутки: перевод TON или оплата
    у провайдера могут прийти позже нашего таймера — деньги человека не теряем."""
    return await all_("SELECT * FROM invoices WHERE provider!='stars' AND "
                      "(status='new' OR (status='expired' AND created_at>?))", (now() - 86400,))


async def pay_invoice(inv_id: int) -> tuple[int, int] | None:
    """new → paid и зачисление. Второй вызов ничего не делает."""
    cur = await run("UPDATE invoices SET status='paid', paid_at=? WHERE id=? AND status IN ('new','expired')",
                    (now(), inv_id))
    if cur.rowcount != 1:
        return None
    row = await get_invoice(inv_id)
    await add_kop(int(row["user_id"]), int(row["kop"]), "topup", f"{row['provider']}#{inv_id}")
    return int(row["user_id"]), int(row["kop"])


async def expire_invoices(older_than: int) -> int:
    cur = await run("UPDATE invoices SET status='expired' WHERE status='new' AND created_at<?",
                    (older_than,))
    return cur.rowcount


# ── Заказы ────────────────────────────────────────────────────────────

async def create_order(uid: int, source: str, item_id: int, country: str,
                       cost_kop: int, price_kop: int) -> int:
    cur = await run("INSERT INTO orders(user_id,source,item_id,country,cost_kop,price_kop,created_at) "
                    "VALUES(?,?,?,?,?,?,?)", (uid, source, item_id, country, cost_kop, price_kop, now()))
    return int(cur.lastrowid)


async def finish_order(oid: int, phone: str, password: str, info: dict, cost_kop: int | None = None) -> None:
    await run("UPDATE orders SET status='done', phone=?, password=?, info=?, done_at=?, "
              "cost_kop=COALESCE(?, cost_kop) WHERE id=?",
              (phone, password, json.dumps(info, ensure_ascii=False), now(), cost_kop, oid))


async def fail_order(oid: int, error: str) -> aiosqlite.Row | None:
    """pending → refunded. Возвращает заказ, если именно этот вызов его закрыл."""
    cur = await run("UPDATE orders SET status='refunded', error=?, done_at=? "
                    "WHERE id=? AND status='pending'", (error[:300], now(), oid))
    if cur.rowcount != 1:
        return None
    return await get_order(oid)


async def get_order(oid: int) -> aiosqlite.Row | None:
    return await one("SELECT * FROM orders WHERE id=?", (oid,))


async def user_orders(uid: int, limit: int = 50) -> list[aiosqlite.Row]:
    return await all_("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))


async def lzt_item_taken(item_id: int) -> bool:
    """Лот уже покупается или куплен нами — второй раз не берём."""
    row = await one("SELECT 1 FROM orders WHERE item_id=? AND status IN ('pending','done') "
                    "UNION SELECT 1 FROM reserve WHERE item_id=?", (item_id, item_id))
    return row is not None


# ── Резерв ────────────────────────────────────────────────────────────

async def reserve_add(item_id: int, country: str, cost_kop: int, phone: str, password: str, info: dict) -> None:
    await run("INSERT OR IGNORE INTO reserve(item_id,country,cost_kop,phone,password,info,bought_at) "
              "VALUES(?,?,?,?,?,?,?)", (item_id, country, cost_kop, phone, password,
                                        json.dumps(info, ensure_ascii=False), now()))


async def reserve_ready(country: str | None = None) -> list[aiosqlite.Row]:
    if country:
        return await all_("SELECT * FROM reserve WHERE status='ready' AND country=? ORDER BY bought_at",
                          (country,))
    return await all_("SELECT * FROM reserve WHERE status='ready' ORDER BY bought_at")


async def reserve_claim(rid: int, status: str = "sold") -> bool:
    cur = await run("UPDATE reserve SET status=? WHERE id=? AND status='ready'", (status, rid))
    return cur.rowcount == 1


async def reserve_release(rid: int) -> None:
    await run("UPDATE reserve SET status='ready' WHERE id=?", (rid,))


# ── Акции ─────────────────────────────────────────────────────────────

async def promos() -> dict[str, int]:
    return {r["country"]: int(r["percent"]) for r in await all_("SELECT * FROM promos")}


async def set_promo(country: str, percent: int) -> None:
    if percent <= 0:
        await run("DELETE FROM promos WHERE country=?", (country,))
    else:
        await run("INSERT INTO promos(country,percent) VALUES(?,?) "
                  "ON CONFLICT(country) DO UPDATE SET percent=excluded.percent", (country, percent))


# ── Статистика ────────────────────────────────────────────────────────

async def stats(since: int = 0) -> dict:
    o = await one("SELECT COUNT(*) n, COALESCE(SUM(price_kop),0) rev, COALESCE(SUM(cost_kop),0) cost "
                  "FROM orders WHERE status='done' AND source!='giveaway' AND done_at>=?", (since,))
    g = await one("SELECT COALESCE(SUM(cost_kop),0) cost FROM orders "
                  "WHERE status='done' AND source='giveaway' AND done_at>=?", (since,))
    t = await one("SELECT COALESCE(SUM(kop),0) s FROM invoices WHERE status='paid' AND paid_at>=?", (since,))
    u = await one("SELECT COUNT(*) n, COALESCE(SUM(kop),0) bal FROM users")
    nu = await one("SELECT COUNT(*) n FROM users WHERE created_at>=?", (since,))
    r = await one("SELECT COUNT(*) n, COALESCE(SUM(cost_kop),0) c FROM reserve WHERE status='ready'")
    return {
        "orders": o["n"], "revenue": o["rev"], "cost": o["cost"], "margin": o["rev"] - o["cost"],
        "giveaway_cost": g["cost"], "topups": t["s"], "users": u["n"], "balances": u["bal"],
        "new_users": nu["n"], "reserve": r["n"], "reserve_cost": r["c"],
    }


async def load_overrides() -> None:
    """Настройки из админки поверх .env (ключи cfg:<ИМЯ> в settings)."""
    rows = await all_("SELECT key, value FROM settings WHERE key LIKE 'cfg:%'")
    config.apply_overrides({r["key"][4:]: r["value"] for r in rows})


async def set_override(name: str, raw: str) -> bool:
    if name not in config.EDITABLE or config.apply_overrides({name: raw}):
        return False
    await set_setting(f"cfg:{name}", raw)
    return True
