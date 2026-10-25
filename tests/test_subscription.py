"""Showly 云端模型订阅（easel/subscription.py）测试。

覆盖：Key 读取与优先级、全通道 .env 写入、无效 Key 不写入、
状态判定、write_env 的就地更新/追加规则。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from easel import subscription


def make_env(env_file: Path, lines: list[str]) -> Path:
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_file


@pytest.fixture()
def env_file(tmp_path: Path) -> Path:
    return tmp_path / ".env"


# ---------------------------------------------------------------- Key 解析

def test_key_from_env_file(env_file: Path):
    make_env(env_file, ["EASEL_SUBSCRIPTION_KEY=sk-test-123"])
    assert subscription.get_subscription_key(env_file) == "sk-test-123"


def test_missing_key_errors_on_enable(env_file: Path):
    with pytest.raises(subscription.SubscriptionError, match="订阅 Key"):
        subscription.enable(env_file=env_file, write=False)


def test_base_url_override(env_file: Path, tmp_path: Path):
    make_env(env_file, ["EASEL_SUBSCRIPTION_BASE_URL=http://localhost:9999/v1"])
    assert subscription.base_url(env_file) == "http://localhost:9999/v1"
    assert subscription.base_url(tmp_path / "none.env") == subscription.SUBSCRIPTION_BASE_URL


# ---------------------------------------------------------------- 探测

def test_probe_invalid_key_reports_clean_error(monkeypatch):
    import urllib.error

    def fake_urlopen(*args, **kwargs):
        raise urllib.error.HTTPError(None, 401, "Unauthorized", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(subscription.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(subscription.SubscriptionError, match="无效"):
        subscription.probe("sk-bad")


def test_probe_unreachable(monkeypatch):
    import urllib.error

    def fake_urlopen(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(subscription.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(subscription.SubscriptionError, match="无法连接"):
        subscription.probe("sk-any")


# ---------------------------------------------------------------- 启用与写入

def _fake_models(monkeypatch, models: list[str]):
    def fake_fetch(key, *, url=None, timeout=15.0, env_file=None):
        return models
    monkeypatch.setattr(subscription, "fetch_models", fake_fetch)


def test_enable_writes_all_channels(env_file: Path, monkeypatch):
    """全通道写入：对话直连三件套 + transport=api + 生图 + 视频 + 音乐。"""
    _fake_models(monkeypatch, ["gpt-5.6-sol", "gpt-image-1", "sora-2", "other"])
    result = subscription.enable("sk-good", env_file=env_file, write=True)
    assert result["ok"] is True
    assert result["chat"]["status"] == "verified"
    assert result["chat"]["model"] == "gpt-5.6-sol"
    assert result["image"]["status"] == "listed"
    assert result["video"]["status"] == "listed"
    assert result["music"]["status"] == "unverified"
    assert result["voice"]["status"] == "local"

    env = subscription._read_env(env_file)
    assert env["EASEL_CHAT_TRANSPORT"] == "api"
    assert env["EASEL_DIRECT_API_BASE_URL"] == subscription.SUBSCRIPTION_BASE_URL
    assert env["EASEL_DIRECT_API_KEY"] == "sk-good"
    assert env["EASEL_DIRECT_API_MODEL"] == "gpt-5.6-sol"
    assert env["IMG_API_KEY"] == "sk-good"
    assert env["IMG_MODEL"] == "gpt-image-1"
    assert env["VIDEO_PROVIDER"] == "openai-compatible"
    assert env["VIDEO_MODEL"] == "sora-2"
    assert env["MUSIC_PROVIDER"] == "suno-compatible"
    assert env["MUSIC_API_KEY"] == "sk-good"
    # 启用 Key 同时回写 EASEL_SUBSCRIPTION_KEY（用户粘贴的 Key 落盘可复用）
    assert env["EASEL_SUBSCRIPTION_KEY"] == "sk-good"
    # Suno 根地址去掉 /v1 尾巴
    assert env["MUSIC_BASE_URL"] == "https://api.openai-next.com"


def test_enable_uses_env_key_when_not_provided(env_file: Path, monkeypatch):
    """入参缺省时回落 .env 的 Key（分发版预填场景）。"""
    make_env(env_file, ["EASEL_SUBSCRIPTION_KEY=sk-from-env"])
    _fake_models(monkeypatch, ["gpt-5.6-sol"])
    result = subscription.enable(env_file=env_file, write=False)
    assert result["keySource"] == "env"
    # 缺生图/视频模型时跳过不写入
    assert result["image"]["status"] == "skipped"
    assert result["video"]["status"] == "skipped"


def test_enable_no_write_when_probe_fails(env_file: Path, monkeypatch):
    import urllib.error

    def fake_urlopen(*args, **kwargs):
        raise urllib.error.HTTPError(None, 403, "Forbidden", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(subscription.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(subscription.SubscriptionError):
        subscription.enable("sk-dead", env_file=env_file, write=True)
    assert not env_file.exists() or "EASEL_DIRECT_API_KEY" not in env_file.read_text(encoding="utf-8")


def test_enable_reuses_existing_env_lines(env_file: Path, monkeypatch):
    """就地更新已有行，不重复追加；注释与无关行保留。"""
    make_env(env_file, [
        "# 用户自己的配置",
        "EASEL_CHAT_TRANSPORT=http",
        "EASEL_DIRECT_API_KEY=sk-old",
    ])
    _fake_models(monkeypatch, ["gpt-5.6-sol"])
    subscription.enable("sk-new", env_file=env_file, write=True)
    text = env_file.read_text(encoding="utf-8")
    assert "# 用户自己的配置" in text
    assert text.count("EASEL_CHAT_TRANSPORT=") == 1
    assert "EASEL_CHAT_TRANSPORT=api" in text
    assert "EASEL_DIRECT_API_KEY=sk-new" in text
    assert "sk-old" not in text


def test_enabled_status_detection(env_file: Path, monkeypatch):
    make_env(env_file, ["EASEL_SUBSCRIPTION_KEY=sk-x"])
    _fake_models(monkeypatch, ["gpt-5.6-sol"])
    assert subscription.status(env_file)["enabled"] is False
    subscription.enable("sk-x", env_file=env_file, write=True)
    info = subscription.status(env_file)
    assert info["enabled"] is True
    assert info["keyPresent"] is True
    assert info["chatModel"] == "gpt-5.6-sol"


def test_write_env_rejects_values_with_control_chars(env_file: Path):
    with pytest.raises(subscription.SubscriptionError):
        subscription.write_env({"X": "a\nb"}, env_file)


def test_model_preference_fallback(monkeypatch, env_file: Path):
    """首选模型不在清单时按偏好顺序取；全都不在则用首个默认。"""
    _fake_models(monkeypatch, ["claude-sonnet-5-5", "unknown-model"])
    result = subscription.enable("sk-x", env_file=env_file, write=False)
    assert result["chat"]["model"] == "claude-sonnet-5-5"


# ---------------------------------------------------------------- bootstrap 零点击

def test_bootstrap_auto_enables_subscription(tmp_path: Path, monkeypatch):
    """模型未配置 + .env 有订阅 Key → bootstrap 自动启用并报告。"""
    import fastapi.testclient as ftc
    import web.app as wa

    env = make_env(tmp_path / ".env", ["EASEL_SUBSCRIPTION_KEY=sk-auto"])
    monkeypatch.setattr(wa, "ENV_FILE", env)
    monkeypatch.setattr(subscription, "ENV_FILE", env)
    # outputs 隔离（harness 设置与安装警告都从这里读）
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    monkeypatch.setattr(wa, "OUTPUTS_DIR", outputs)
    # runtime 判定不带旧环境干扰
    monkeypatch.delenv("EASEL_CHAT_TRANSPORT", raising=False)
    monkeypatch.delenv("EASEL_AGENT_RUNTIME", raising=False)
    _fake_models(monkeypatch, ["gpt-5.6-sol"])

    with ftc.TestClient(wa.app, base_url="http://127.0.0.1") as client:
        first = client.get("/api/settings/bootstrap").json()
        assert first["subscriptionAutoEnabled"] is True
        assert first["modelConfigured"] is True
        second = client.get("/api/settings/bootstrap").json()
        assert second["subscriptionAutoEnabled"] is False  # 已配置不再重复启用
    assert subscription.is_enabled(env)


def test_bootstrap_no_auto_enable_without_key(tmp_path: Path, monkeypatch):
    import fastapi.testclient as ftc
    import web.app as wa

    env = make_env(tmp_path / ".env", [])
    monkeypatch.setattr(wa, "ENV_FILE", env)
    monkeypatch.setattr(subscription, "ENV_FILE", env)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    monkeypatch.setattr(wa, "OUTPUTS_DIR", outputs)
    monkeypatch.delenv("EASEL_CHAT_TRANSPORT", raising=False)
    monkeypatch.delenv("EASEL_AGENT_RUNTIME", raising=False)

    with ftc.TestClient(wa.app, base_url="http://127.0.0.1") as client:
        data = client.get("/api/settings/bootstrap").json()
    assert data["subscriptionAutoEnabled"] is False
    assert not env.read_text(encoding="utf-8").strip()
