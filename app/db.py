import logging
from pathlib import Path

import aiosqlite

from app.config import get_settings

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


async def connect(db_path: str | None = None) -> aiosqlite.Connection:
    db_path = db_path or get_settings().db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def init_db(db_path: str | None = None) -> None:
    conn = await connect(db_path)
    try:
        schema = _SCHEMA_PATH.read_text()
        await conn.executescript(schema)
        await conn.commit()
        logger.info("Database schema applied")
    finally:
        await conn.close()


async def get_db():
    conn = await connect()
    try:
        yield conn
    finally:
        await conn.close()


async def save_document(
    conn: aiosqlite.Connection,
    *,
    url: str,
    final_url: str,
    title: str,
    source: str,
    content_type: str,
    content: str,
    status: str = "ok",
    error: str = "",
) -> int:
    cur = await conn.execute(
        "INSERT INTO documents (url, final_url, title, source, content_type,"
        " content, status, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (url, final_url, title, source, content_type, content, status, error),
    )
    await conn.commit()
    return cur.lastrowid


async def get_document(conn: aiosqlite.Connection, doc_id: int) -> dict | None:
    rows = await conn.execute_fetchall(
        "SELECT * FROM documents WHERE id = ?", (doc_id,)
    )
    return dict(rows[0]) if rows else None


async def delete_document(conn: aiosqlite.Connection, doc_id: int) -> bool:
    """Delete a document from history. Returns True if a row was removed."""
    cur = await conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    await conn.commit()
    return cur.rowcount > 0


async def list_documents(
    conn: aiosqlite.Connection, limit: int = 50, offset: int = 0
) -> list[dict]:
    rows = await conn.execute_fetchall(
        "SELECT id, url, title, source, content_type, status, created_at"
        " FROM documents ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return [dict(r) for r in rows]


async def count_documents(conn: aiosqlite.Connection) -> int:
    cur = await conn.execute("SELECT COUNT(*) FROM documents")
    row = await cur.fetchone()
    return int(row[0])


async def check_and_record_rate_limit(
    conn: aiosqlite.Connection,
    *,
    ip: str,
    route: str,
    limit: int,
    window_seconds: int,
) -> bool:
    """Record a hit for (ip, route) and return whether it's within `limit`
    hits in the trailing `window_seconds`. Also prunes hits for this route
    older than the window, so the table doesn't grow unbounded."""
    offset = f"-{window_seconds} seconds"
    await conn.execute(
        "DELETE FROM rate_limit_hits WHERE route = ?"
        " AND created_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
        (route, offset),
    )
    cur = await conn.execute(
        "SELECT COUNT(*) FROM rate_limit_hits WHERE route = ? AND ip = ?"
        " AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
        (route, ip, offset),
    )
    row = await cur.fetchone()
    if row[0] >= limit:
        await conn.commit()
        return False
    await conn.execute(
        "INSERT INTO rate_limit_hits (ip, route) VALUES (?, ?)", (ip, route)
    )
    await conn.commit()
    return True
