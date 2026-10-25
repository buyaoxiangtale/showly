"""MCP 账号/套餐/积分存储层（SQLite + 版本化迁移，模式复用 easel/promotion/db.py）。

数据库位置：默认 ``outputs/_mcp/mcp.db``，可用 ``SHOWLY_MCP_DB`` 覆盖（测试隔离）。
连接为线程本地（FastMCP 工具调用在事件循环线程、admin 在主线程），WAL + 外键。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_LOCAL = threading.local()

MIGRATIONS: list[str] = [
    # v1：账号体系全量
    """
    CREATE TABLE IF NOT EXISTS plans (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        allowed_tools TEXT NOT NULL DEFAULT '[]',
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""",
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        plan_id TEXT NOT NULL REFERENCES plans(id),
        credits REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """
    CREATE TABLE IF NOT EXISTS credit_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        delta REAL NOT NULL,
        kind TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        usage_id TEXT,
        created_at TEXT NOT NULL
    )""",
    """
    CREATE TABLE IF NOT EXISTS usage_records (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        tool TEXT NOT NULL,
        credits_cost REAL NOT NULL DEFAULT 0,
        ok INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        elapsed_ms INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
]

# 内置套餐（首次建库时写入；不覆盖已有行）
BUILTIN_PLANS: list[dict] = [
    {"id": "free", "name": "Free", "allowed_tools": ["chat"], "note": "送 100 积分，仅文本生成"},
    {"id": "starter", "name": "Starter", "allowed_tools": ["chat", "image", "music"],
     "note": "月送 1000 积分，文本/生图/音乐"},
    {"id": "pro", "name": "Pro", "allowed_tools": ["chat", "image", "music", "video"],
     "note": "月送 5000 积分，全部工具"},
]


def db_path() -> Path:
    override = os.environ.get("SHOWLY_MCP_DB", "").strip()
    path = Path(override) if override else PROJECT_ROOT / "outputs" / "_mcp" / "mcp.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _new_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    for version, statement in enumerate(MIGRATIONS, start=1):
        if version in applied:
            continue
        conn.executescript(statement)
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
    # 内置套餐（不覆盖已有）
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for plan in BUILTIN_PLANS:
        conn.execute(
            "INSERT OR IGNORE INTO plans (id, name, allowed_tools, note, created_at)"
            " VALUES (?,?,?,?,?)",
            (plan["id"], plan["name"], _json_tools(plan["allowed_tools"]), plan["note"], ts),
        )
    conn.commit()


def _json_tools(tools: list[str]) -> str:
    import json
    return json.dumps(tools, ensure_ascii=False)


def connect() -> sqlite3.Connection:
    """当前线程连接（线程本地）；首次自动建库迁移。"""
    if not getattr(_LOCAL, "initialized", False):
        _migrate(_new_connection())
        _LOCAL.initialized = True
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        conn = _new_connection()
        _LOCAL.conn = conn
    return conn


def reset_thread_connection() -> None:
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        del _LOCAL.conn
    _LOCAL.initialized = False
