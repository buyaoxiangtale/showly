"""Showly MCP 服务测试：鉴权、套餐白名单、积分预检/扣费、失败不扣费、admin CLI。

模型后端调用全部 mock（不依赖网络与真实 Key）；工具函数直接调用原始
``_chat_tool`` 等（鉴权 Token 通过 monkeypatch 请求头取值函数注入）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from showly_mcp import accounts_db, backend, billing, server


@pytest.fixture()
def mcp_db(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOWLY_MCP_DB", str(tmp_path / "mcp.db"))
    accounts_db.reset_thread_connection()
    accounts_db.connect()
    yield accounts_db
    accounts_db.reset_thread_connection()


@pytest.fixture()
def account(mcp_db):
    return billing.create_account("测试用户", "pro", initial_credits=100)


def patch_headers(monkeypatch, token: str):
    """把「从请求上下文取 Bearer Token」替换为固定值（模拟鉴权头）。"""
    monkeypatch.setattr(server, "_current_token", lambda: token)


def run(tool_fn, **kwargs):
    return asyncio.run(tool_fn(**kwargs))


# ---------------------------------------------------------------- 账号与鉴权

def test_builtin_plans_seeded(mcp_db):
    plans = billing.list_plans()
    ids = {p["id"] for p in plans}
    assert {"free", "starter", "pro"} <= ids
    pro = next(p for p in plans if p["id"] == "pro")
    assert set(pro["allowed_tools"]) == {"chat", "image", "music", "video"}


def test_create_account_returns_token_once(mcp_db):
    account = billing.create_account("张三", "starter", initial_credits=50)
    assert account["token"].startswith("sk-mcp-")
    found = billing.authenticate(account["token"])
    assert found["id"] == account["id"]
    assert found["allowed_tools"] == ["chat", "image", "music"]


def test_authenticate_rejects_bad_or_suspended(mcp_db, account):
    with pytest.raises(billing.AuthError):
        billing.authenticate("sk-mcp-not-a-real-token")
    with pytest.raises(billing.AuthError):
        billing.authenticate("")
    billing.set_status(account["id"], "suspended")
    with pytest.raises(billing.AuthError):
        billing.authenticate(account["token"])


# ---------------------------------------------------------------- 预检与扣费

def test_precheck_plan_whitelist(mcp_db):
    free = billing.create_account("免费", "free", initial_credits=10)
    with pytest.raises(billing.QuotaError, match="不含工具 image"):
        billing.precheck(billing.authenticate(free["token"]), "image")
    assert billing.precheck(billing.authenticate(free["token"]), "chat") == 1


def test_precheck_insufficient_credits(mcp_db):
    poor = billing.create_account("穷", "pro", initial_credits=2)
    with pytest.raises(billing.QuotaError, match="积分不足"):
        billing.precheck(billing.authenticate(poor["token"]), "image")
    assert billing.precheck(billing.authenticate(poor["token"]), "chat") == 1


def test_charge_success_and_failure_paths(mcp_db, account):
    remaining = billing.charge(account["id"], "image", 5, ok=True, elapsed_ms=42)
    assert remaining == 95
    billing.record_failure(account["id"], "video", "HTTP 500")
    assert billing.get_account(account["id"])["credits"] == 95
    usage = billing.account_usage(account["id"])
    by_tool = {row["tool"]: row for row in usage}
    assert by_tool["image"]["ok"] == 1 and by_tool["image"]["credits_cost"] == 5
    assert by_tool["video"]["ok"] == 0 and by_tool["video"]["credits_cost"] == 0


def test_ledger_records_topup_and_usage(mcp_db, account):
    billing.add_credits(account["id"], 200, "测试充值")
    billing.charge(account["id"], "chat", 1, ok=True)
    conn = accounts_db.connect()
    rows = conn.execute(
        "SELECT kind, delta FROM credit_ledger WHERE account_id=? ORDER BY id",
        (account["id"],)).fetchall()
    kinds = {(r["kind"], r["delta"]) for r in rows}
    assert ("grant", 100.0) in kinds
    assert ("topup", 200.0) in kinds
    assert ("usage", -1.0) in kinds


# ---------------------------------------------------------------- MCP 工具（协议层）

def test_chat_tool_charges_and_appends_attribution(mcp_db, account, monkeypatch):
    monkeypatch.setattr(backend, "chat", lambda prompt, system=None: "生成的文案")
    patch_headers(monkeypatch, account["token"])
    result = run(server._chat_tool, prompt="写一句小红书文案")
    assert "生成的文案" in result["text"]
    assert result["text"].rstrip().endswith(server.ATTRIBUTION)
    assert result["credits_remaining"] == 99


def test_tool_rejects_without_token(mcp_db, monkeypatch):
    patch_headers(monkeypatch, "")
    result = run(server._chat_tool, prompt="hi")
    assert "鉴权失败" in result["error"]


def test_tool_plan_rejected_before_backend(mcp_db, monkeypatch):
    free = billing.create_account("免费", "free", initial_credits=100)
    called = []
    monkeypatch.setattr(backend, "image", lambda prompt, size="1024x1024": called.append(1))
    patch_headers(monkeypatch, free["token"])
    result = run(server._image_tool, prompt="封面")
    assert "不含工具 image" in result["error"]
    assert not called  # 套餐预检失败时后端根本没被调用
    assert billing.get_account(free["id"])["credits"] == 100


def test_tool_backend_failure_no_charge(mcp_db, account, monkeypatch):
    def boom(prompt, size="1024x1024"):
        raise backend.BackendError("HTTP 503")

    monkeypatch.setattr(backend, "image", boom)
    patch_headers(monkeypatch, account["token"])
    result = run(server._image_tool, prompt="封面")
    assert "未扣积分" in result["error"]
    assert billing.get_account(account["id"])["credits"] == 100
    usage = billing.account_usage(account["id"])
    assert usage and usage[0]["ok"] == 0 and "503" in usage[0]["error"]


def test_my_account_tool_reports_pricing(mcp_db, account, monkeypatch):
    patch_headers(monkeypatch, account["token"])
    result = run(server._my_account_tool)
    assert result["plan"] == "Pro"
    assert result["credits_remaining"] == 100
    assert result["pricing"]["video"] == 50


# ---------------------------------------------------------------- admin CLI

def test_admin_cli_end_to_end(mcp_db, capsys):
    from showly_mcp import admin
    assert admin.main(["create-account", "--name", "李四", "--plan", "starter",
                       "--credits", "60"]) == 0
    out = capsys.readouterr().out
    assert "sk-mcp-" in out and "只显示这一次" in out
    assert admin.main(["list"]) == 0
    listing = capsys.readouterr().out
    account_id = [line.split()[0] for line in listing.splitlines()
                  if line.startswith("acc_")][0]
    assert admin.main(["add-credits", "--account", account_id, "--amount", "40"]) == 0
    assert "100" in capsys.readouterr().out
    assert admin.main(["set-plan", "--account", account_id, "--plan", "pro"]) == 0
    assert admin.main(["plans"]) == 0
    assert admin.main(["usage", "--account", account_id]) == 0
    assert admin.main(["add-credits", "--account", "acc_missing", "--amount", "1"]) == 1


def test_charge_concurrent_guard_never_negative(mcp_db, account):
    """并发兜底：同余额两次扣费，第二次被条件更新拒绝且不落负数。"""
    billing.charge(account["id"], "chat", 1, ok=True)
    # 直接模拟第二笔竞争同余额（预检时余额足够，执行时已被扣）
    with pytest.raises(billing.QuotaError, match="并发"):
        billing.charge(account["id"], "image", 100, ok=True)  # 99 < 100 触发条件拒绝
    assert billing.get_account(account["id"])["credits"] == 99
