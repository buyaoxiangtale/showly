"""账号鉴权与套餐/积分计费。

链路：Token（哈希）→ 账号状态 → 套餐工具白名单 → 余额预检 →（执行）→ 成功扣费。
失败不扣费；扣费用事务保证「余额 + 流水 + 用量」一致。
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone

from showly_mcp import accounts_db

# 工具单价（积分/次）。video/music 默认套餐不含，商用节奏由套餐控制。
TOOL_PRICING: dict[str, float] = {"chat": 1, "image": 5, "music": 10, "video": 50}


class AuthError(ValueError):
    """鉴权失败（Token 无效/账号停用）。"""


class QuotaError(ValueError):
    """配额不满足（套餐外工具/积分不足），消息直接展示给用户。"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 账号管理

def create_account(name: str, plan_id: str, *, initial_credits: float = 0) -> dict:
    conn = accounts_db.connect()
    if conn.execute("SELECT 1 FROM plans WHERE id=?", (plan_id,)).fetchone() is None:
        raise QuotaError(f"未知套餐：{plan_id}")
    account_id = f"acc_{uuid.uuid4().hex[:12]}"
    token = f"sk-mcp-{secrets.token_urlsafe(32)}"
    ts = now()
    conn.execute(
        "INSERT INTO accounts (id, name, token_hash, plan_id, credits, status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (account_id, name.strip(), _hash_token(token), plan_id, float(initial_credits),
         "active", ts, ts),
    )
    if initial_credits:
        conn.execute(
            "INSERT INTO credit_ledger (account_id, delta, kind, note, created_at)"
            " VALUES (?,?,?,?,?)",
            (account_id, float(initial_credits), "grant", "开户赠送", ts),
        )
    conn.commit()
    # Token 明文只在创建时返回一次；库里只有哈希
    return {"id": account_id, "name": name.strip(), "plan": plan_id,
            "credits": float(initial_credits), "token": token}


def authenticate(token: str) -> dict:
    """Bearer Token → 账号（含套餐工具白名单）。失败抛 AuthError。"""
    if not token or not token.startswith("sk-mcp-"):
        raise AuthError("无效的 MCP Token")
    conn = accounts_db.connect()
    row = conn.execute(
        "SELECT a.id, a.name, a.credits, a.status, a.plan_id, p.allowed_tools, p.name AS plan_name"
        " FROM accounts a JOIN plans p ON p.id = a.plan_id WHERE a.token_hash = ?",
        (_hash_token(token.strip()),)).fetchone()
    if row is None:
        raise AuthError("无效的 MCP Token")
    if row["status"] != "active":
        raise AuthError(f"账号已{row['status']}，请联系管理员")
    import json
    return {
        "id": row["id"], "name": row["name"], "credits": float(row["credits"]),
        "plan": row["plan_id"], "plan_name": row["plan_name"],
        "allowed_tools": json.loads(row["allowed_tools"] or "[]"),
    }


# ---------------------------------------------------------------- 预检与扣费

def precheck(account: dict, tool: str) -> float:
    """调用前预检：套餐白名单 + 余额。返回单价；不满足抛 QuotaError（含余额与所需）。"""
    price = TOOL_PRICING.get(tool)
    if price is None:
        raise QuotaError(f"未知工具：{tool}")
    if tool not in account["allowed_tools"]:
        raise QuotaError(
            f"当前套餐（{account['plan_name']}）不含工具 {tool}，请联系管理员升级套餐")
    if account["credits"] < price:
        raise QuotaError(
            f"积分不足：调用 {tool} 需要 {price:g} 积分，当前余额 {account['credits']:g}，请充值")
    return price


def charge(account_id: str, tool: str, price: float, *, ok: bool, error: str = "",
           elapsed_ms: int = 0) -> float:
    """登记用量；成功才扣积分（事务：余额 + 流水 + 用量）。返回剩余积分。"""
    conn = accounts_db.connect()
    usage_id = f"use_{uuid.uuid4().hex[:12]}"
    ts = now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO usage_records (id, account_id, tool, credits_cost, ok, error,"
            " elapsed_ms, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (usage_id, account_id, tool, price if ok else 0, 1 if ok else 0,
             error[:300], elapsed_ms, ts),
        )
        if ok:
            # credits >= price 条件更新兜底并发：两个请求同余额双双通过预检时，
            # 后提交的事务因条件不满足中止，不会扣成负数。
            conn.execute(
                "UPDATE accounts SET credits = credits - ?, updated_at = ?"
                " WHERE id = ? AND credits >= ?",
                (price, ts, account_id, price))
            if conn.execute("SELECT changes()").fetchone()[0] == 0:
                conn.rollback()
                raise QuotaError(
                    f"积分不足：调用 {tool} 需要 {price:g} 积分（并发扣减后余额已不足），请充值")
            conn.execute(
                "INSERT INTO credit_ledger (account_id, delta, kind, note, usage_id,"
                 " created_at) VALUES (?,?,?,?,?,?)",
                (account_id, -price, "usage", f"{tool} 调用", usage_id, ts))
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    row = conn.execute("SELECT credits FROM accounts WHERE id=?", (account_id,)).fetchone()
    return float(row["credits"])


# ---------------------------------------------------------------- 管理操作

def add_credits(account_id: str, amount: float, note: str = "") -> dict:
    if amount <= 0:
        raise QuotaError("充值数额必须为正数")
    conn = accounts_db.connect()
    conn.execute(
        "UPDATE accounts SET credits = credits + ?, updated_at = ? WHERE id = ?",
        (amount, now(), account_id))
    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        conn.commit()
        raise QuotaError(f"账号不存在：{account_id}")
    conn.execute(
        "INSERT INTO credit_ledger (account_id, delta, kind, note, created_at)"
        " VALUES (?,?,?,?,?)", (account_id, amount, "topup", note or "充值", now()))
    conn.commit()
    return get_account(account_id)


def set_plan(account_id: str, plan_id: str) -> dict:
    conn = accounts_db.connect()
    if conn.execute("SELECT 1 FROM plans WHERE id=?", (plan_id,)).fetchone() is None:
        raise QuotaError(f"未知套餐：{plan_id}")
    conn.execute("UPDATE accounts SET plan_id=?, updated_at=? WHERE id=?",
                 (plan_id, now(), account_id))
    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        conn.commit()
        raise QuotaError(f"账号不存在：{account_id}")
    conn.commit()
    return get_account(account_id)


def set_status(account_id: str, status: str) -> dict:
    if status not in ("active", "suspended"):
        raise QuotaError("状态只能是 active / suspended")
    conn = accounts_db.connect()
    conn.execute("UPDATE accounts SET status=?, updated_at=? WHERE id=?",
                 (status, now(), account_id))
    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        conn.commit()
        raise QuotaError(f"账号不存在：{account_id}")
    conn.commit()
    return get_account(account_id)


def get_account(account_id: str) -> dict:
    conn = accounts_db.connect()
    row = conn.execute(
        "SELECT a.id, a.name, a.plan_id, a.credits, a.status, a.created_at,"
        " p.name AS plan_name FROM accounts a JOIN plans p ON p.id = a.plan_id"
        " WHERE a.id = ?", (account_id,)).fetchone()
    if row is None:
        raise QuotaError(f"账号不存在：{account_id}")
    return dict(row)


def list_accounts() -> list[dict]:
    conn = accounts_db.connect()
    rows = conn.execute(
        "SELECT a.id, a.name, a.plan_id, p.name AS plan_name, a.credits, a.status,"
        " a.created_at, (SELECT COUNT(*) FROM usage_records u WHERE u.account_id = a.id"
        "   AND u.ok = 1) AS total_calls"
        " FROM accounts a JOIN plans p ON p.id = a.plan_id ORDER BY a.created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def list_plans() -> list[dict]:
    import json
    conn = accounts_db.connect()
    rows = conn.execute("SELECT * FROM plans ORDER BY created_at").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["allowed_tools"] = json.loads(item["allowed_tools"] or "[]")
        except json.JSONDecodeError:
            item["allowed_tools"] = []
        result.append(item)
    return result


def account_usage(account_id: str, limit: int = 20) -> list[dict]:
    conn = accounts_db.connect()
    rows = conn.execute(
        "SELECT tool, credits_cost, ok, error, elapsed_ms, created_at FROM usage_records"
        " WHERE account_id = ? ORDER BY created_at DESC LIMIT ?",
        (account_id, limit)).fetchall()
    return [dict(r) for r in rows]


def record_failure(account_id: str, tool: str, error: str, elapsed_ms: int = 0) -> None:
    """执行失败也登记用量（不扣积分），便于观测。"""
    conn = accounts_db.connect()
    conn.execute(
        "INSERT INTO usage_records (id, account_id, tool, credits_cost, ok, error,"
        " elapsed_ms, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (f"use_{uuid.uuid4().hex[:12]}", account_id, tool, 0, 0, error[:300],
         elapsed_ms, now()))
    conn.commit()
