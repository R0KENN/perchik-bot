import sqlite3
from contextlib import contextmanager
from datetime import date

from config import DB_PATH
from parser import ParsedShift

SCHEMA = """
CREATE TABLE IF NOT EXISTS shifts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    thread_id   INTEGER,
    shift_date  TEXT    NOT NULL,
    time_start  TEXT,
    time_end    TEXT,
    hours       REAL,
    total_usd   REAL    NOT NULL DEFAULT 0,
    raw_text    TEXT,
    created_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS entries (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
    site     TEXT    NOT NULL,
    tokens   REAL    DEFAULT 0,
    usd      REAL    DEFAULT 0,
    follows  INTEGER DEFAULT 0,
    likes    INTEGER DEFAULT 0,
    score    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_shift_date ON shifts (shift_date);
CREATE INDEX IF NOT EXISTS idx_entry_shift ON entries (shift_id);

CREATE TABLE IF NOT EXISTS goals (
    ym     TEXT PRIMARY KEY,
    amount REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# follows в чеке — это ОБЩЕЕ число подписчиков на конец смены (снимок).
# Прирост = разница со снимком предыдущей смены того же сайта.
GAINS_CTE = """
WITH ordered AS (
    SELECT s.shift_date AS d, s.id AS sid, e.site AS site, e.follows AS f,
           LAG(e.follows) OVER (PARTITION BY e.site ORDER BY s.shift_date, s.id) AS pf
    FROM entries e JOIN shifts s ON s.id = e.shift_id
    WHERE e.follows > 0
),
gains AS (
    SELECT d, site,
           CASE WHEN pf IS NULL OR f < pf THEN 0 ELSE f - pf END AS gain
    FROM ordered
)
"""


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


def upsert_shift(chat_id: int, message_id: int, thread_id: int | None, p: ParsedShift) -> int:
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO shifts (chat_id, message_id, thread_id, shift_date,
                                time_start, time_end, hours, total_usd, raw_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (chat_id, message_id) DO UPDATE SET
                shift_date = excluded.shift_date,
                time_start = excluded.time_start,
                time_end   = excluded.time_end,
                hours      = excluded.hours,
                total_usd  = excluded.total_usd,
                raw_text   = excluded.raw_text
            """,
            (chat_id, message_id, thread_id, p.shift_date.isoformat(),
             p.time_start, p.time_end, p.hours, p.total_usd, p.raw_text),
        )
        shift_id = cur.execute(
            "SELECT id FROM shifts WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        ).fetchone()["id"]
        cur.execute("DELETE FROM entries WHERE shift_id = ?", (shift_id,))
        cur.executemany(
            "INSERT INTO entries (shift_id, site, tokens, usd, follows, likes, score)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(shift_id, e.site, e.tokens, e.usd, e.follows, e.likes, e.score) for e in p.entries],
        )
        return shift_id


def delete_shift(chat_id: int, message_id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM shifts WHERE chat_id = ? AND message_id = ?", (chat_id, message_id)
        )
        return cur.rowcount > 0


def dedupe() -> int:
    """Удаляет повторы: одна дата + одинаковый тотал + одинаковое начало смены."""
    with db() as conn:
        cur = conn.execute(
            """
            DELETE FROM shifts WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY shift_date, ROUND(total_usd, 2), COALESCE(time_start, '')
                        ORDER BY id
                    ) AS rn FROM shifts
                ) WHERE rn > 1
            )
            """
        )
        return cur.rowcount


def period_summary(d_from: date, d_to: date) -> dict:
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS shifts, COALESCE(SUM(total_usd), 0) AS usd,"
            " COALESCE(SUM(hours), 0) AS hours FROM shifts WHERE shift_date BETWEEN ? AND ?",
            (d_from.isoformat(), d_to.isoformat()),
        ).fetchone()
        tokens = conn.execute(
            "SELECT COALESCE(SUM(e.tokens), 0) AS t FROM entries e"
            " JOIN shifts s ON s.id = e.shift_id WHERE s.shift_date BETWEEN ? AND ?",
            (d_from.isoformat(), d_to.isoformat()),
        ).fetchone()["t"]
        best = conn.execute(
            "SELECT shift_date, total_usd FROM shifts WHERE shift_date BETWEEN ? AND ?"
            " ORDER BY total_usd DESC LIMIT 1",
            (d_from.isoformat(), d_to.isoformat()),
        ).fetchone()

    return {
        "shifts": row["shifts"],
        "usd": row["usd"],
        "hours": row["hours"],
        "tokens": tokens,
        "best_date": best["shift_date"] if best else None,
        "best_usd": best["total_usd"] if best else 0,
    }


def by_site(d_from: date, d_to: date) -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            """
            SELECT e.site,
                   COALESCE(SUM(e.usd), 0)    AS usd,
                   COALESCE(SUM(e.tokens), 0) AS tokens,
                   COUNT(DISTINCT s.id)       AS shifts
            FROM entries e JOIN shifts s ON s.id = e.shift_id
            WHERE s.shift_date BETWEEN ? AND ?
            GROUP BY e.site
            ORDER BY usd DESC, e.site
            """,
            (d_from.isoformat(), d_to.isoformat()),
        ).fetchall()


def gains_by_site(d_from: date, d_to: date) -> dict[str, int]:
    with db() as conn:
        rows = conn.execute(
            GAINS_CTE + "SELECT site, SUM(gain) AS g FROM gains"
            " WHERE d BETWEEN ? AND ? GROUP BY site",
            (d_from.isoformat(), d_to.isoformat()),
        ).fetchall()
    return {r["site"]: int(r["g"] or 0) for r in rows}


def gains_daily(d_from: date, d_to: date) -> dict[str, int]:
    with db() as conn:
        rows = conn.execute(
            GAINS_CTE + "SELECT d, SUM(gain) AS g FROM gains"
            " WHERE d BETWEEN ? AND ? GROUP BY d",
            (d_from.isoformat(), d_to.isoformat()),
        ).fetchall()
    return {r["d"]: int(r["g"] or 0) for r in rows}


def current_followers() -> list[sqlite3.Row]:
    """Последний известный снимок подписчиков по каждому сайту."""
    with db() as conn:
        return conn.execute(
            """
            SELECT site, follows, shift_date FROM (
                SELECT e.site AS site, e.follows AS follows, s.shift_date AS shift_date,
                       ROW_NUMBER() OVER (
                           PARTITION BY e.site ORDER BY s.shift_date DESC, s.id DESC
                       ) AS rn
                FROM entries e JOIN shifts s ON s.id = e.shift_id
                WHERE e.follows > 0
            ) WHERE rn = 1 ORDER BY follows DESC
            """
        ).fetchall()


def followers_series(d_from: date, d_to: date) -> dict[str, list[tuple[date, int]]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT s.shift_date AS d, e.site AS site, e.follows AS f"
            " FROM entries e JOIN shifts s ON s.id = e.shift_id"
            " WHERE e.follows > 0 AND s.shift_date BETWEEN ? AND ?"
            " ORDER BY s.shift_date, s.id",
            (d_from.isoformat(), d_to.isoformat()),
        ).fetchall()
    out: dict[str, list[tuple[date, int]]] = {}
    for r in rows:
        out.setdefault(r["site"], []).append((date.fromisoformat(r["d"]), int(r["f"])))
    return out


def daily_money(d_from: date, d_to: date) -> dict[str, float]:
    with db() as conn:
        rows = conn.execute(
            "SELECT shift_date, SUM(total_usd) AS usd FROM shifts"
            " WHERE shift_date BETWEEN ? AND ? GROUP BY shift_date",
            (d_from.isoformat(), d_to.isoformat()),
        ).fetchall()
    return {r["shift_date"]: r["usd"] for r in rows}


def first_date() -> date | None:
    with db() as conn:
        row = conn.execute("SELECT MIN(shift_date) AS d FROM shifts").fetchone()
    return date.fromisoformat(row["d"]) if row and row["d"] else None


def last_shifts(limit: int = 5) -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            "SELECT shift_date, total_usd, time_start, time_end FROM shifts"
            " ORDER BY shift_date DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()

def all_sites() -> list[sqlite3.Row]:
    """Все площадки, что вообще встречались в чеках."""
    with db() as conn:
        return conn.execute(
            "SELECT site, COUNT(*) AS n, SUM(usd) AS usd FROM entries"
            " GROUP BY site ORDER BY n DESC"
        ).fetchall()



# ---------- цели на месяц ----------

def set_goal(ym: str, amount: float) -> None:
    """ym в формате '2026-08'. amount <= 0 — снять цель."""
    with db() as conn:
        if amount <= 0:
            conn.execute("DELETE FROM goals WHERE ym = ?", (ym,))
        else:
            conn.execute(
                "INSERT INTO goals (ym, amount) VALUES (?, ?)"
                " ON CONFLICT (ym) DO UPDATE SET amount = excluded.amount",
                (ym, amount),
            )


def get_goal(ym: str) -> float | None:
    with db() as conn:
        row = conn.execute("SELECT amount FROM goals WHERE ym = ?", (ym,)).fetchone()
    return row["amount"] if row else None


# ---------- служебная память бота (для автоотчётов) ----------

def meta_get(key: str) -> str | None:
    with db() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def meta_set(key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ---------- аналитика: дни недели, часы, эффективность ----------

def by_weekday(d_from: date, d_to: date) -> list[sqlite3.Row]:
    """0 = воскресенье … 6 = суббота (как в strftime('%w'))."""
    with db() as conn:
        return conn.execute(
            "SELECT CAST(strftime('%w', shift_date) AS INTEGER) AS dow,"
            " COUNT(*) AS shifts,"
            " COALESCE(SUM(total_usd), 0) AS usd,"
            " COALESCE(SUM(hours), 0) AS hours"
            " FROM shifts WHERE shift_date BETWEEN ? AND ?"
            " GROUP BY dow",
            (d_from.isoformat(), d_to.isoformat()),
        ).fetchall()


def by_hour(d_from: date, d_to: date) -> list[sqlite3.Row]:
    """Группировка по часу начала смены."""
    with db() as conn:
        return conn.execute(
            "SELECT CAST(substr(time_start, 1, 2) AS INTEGER) AS h,"
            " COUNT(*) AS shifts,"
            " COALESCE(SUM(total_usd), 0) AS usd,"
            " COALESCE(SUM(hours), 0) AS hours"
            " FROM shifts WHERE shift_date BETWEEN ? AND ?"
            "   AND time_start IS NOT NULL AND time_start <> ''"
            " GROUP BY h ORDER BY h",
            (d_from.isoformat(), d_to.isoformat()),
        ).fetchall()


def site_efficiency(d_from: date, d_to: date) -> list[sqlite3.Row]:
    """Доход и часы по площадкам (часы смены засчитываются сайту, если он был в чеке)."""
    with db() as conn:
        return conn.execute(
            "SELECT e.site AS site,"
            " COALESCE(SUM(e.usd), 0) AS usd,"
            " COALESCE(SUM(CASE WHEN e.usd > 0 THEN s.hours ELSE 0 END), 0) AS hours,"
            " COUNT(DISTINCT CASE WHEN e.usd > 0 THEN s.id END) AS shifts"
            " FROM entries e JOIN shifts s ON s.id = e.shift_id"
            " WHERE s.shift_date BETWEEN ? AND ?"
            " GROUP BY e.site ORDER BY usd DESC",
            (d_from.isoformat(), d_to.isoformat()),
        ).fetchall()
