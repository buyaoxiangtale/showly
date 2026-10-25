"""Showly 云端模型订阅：一键配置全部模型通道。

设计约定：
- 订阅 Key 只存 ``.env`` 的 ``EASEL_SUBSCRIPTION_KEY``，代码不内置任何 Key。
  分发版由打包方预填 ``.env``；用户也可在界面粘贴自己的 Key（写入同名键覆盖）。
- 端点默认 ``https://api.openai-next.com/v1``（OpenAI 兼容，Bearer 鉴权），
  可用 ``EASEL_SUBSCRIPTION_BASE_URL`` 覆盖（测试/换域名不改代码）。
- 启用 = 探测 Key → 一次性写入对话/生图/视频/音乐通道 → 返回逐通道结果；
  语音与转写保持本地免费方案（edge-tts / faster-whisper），零配置。
- 对话走直连模式（``EASEL_CHAT_TRANSPORT=api``），无网关、无 OpenClaw 依赖；
  ``easel/harnesses/store.py`` 会把 transport=api 强制为 api 运行时。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

SUBSCRIPTION_BASE_URL = "https://api.openai-next.com/v1"
SUBSCRIPTION_KEY_ENV = "EASEL_SUBSCRIPTION_KEY"
SUBSCRIPTION_BASE_ENV = "EASEL_SUBSCRIPTION_BASE_URL"

# 各通道默认模型：按优先级取第一个出现在服务 /models 清单里的
CHAT_MODEL_PREFERENCES = ("gpt-5.6-sol", "gpt-5.6-terra", "claude-sonnet-5-5",
                          "claude-sonnet-5", "glm-5.3", "deepseek-v4-pro")
IMAGE_MODEL_PREFERENCES = ("gpt-image-1", "gpt-image-2")
VIDEO_MODEL_PREFERENCES = ("sora-2",)
# Suno 协议与 OpenAI /models 不互通，无法免费验证，写入后标记未验证
MUSIC_MODEL_DEFAULT = "chirp-v5"


class SubscriptionError(ValueError):
    """订阅配置错误（Key 无效、端点不可达等），消息可直接展示给用户。"""


def _read_env(env_file: Path | None = None) -> dict[str, str]:
    path = env_file or ENV_FILE
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def write_env(updates: dict[str, str], env_file: Path | None = None) -> None:
    """就地更新/追加 .env（原子写，保留原有行与注释；空值跳过）。"""
    updates = {k: v.strip() for k, v in updates.items() if k and v.strip()}
    if not updates:
        return
    for key, value in updates.items():
        if any(ch.isspace() for ch in value) or any(ord(c) < 32 for c in value):
            raise SubscriptionError(f"配置值包含非法字符：{key}")
    path = env_file or ENV_FILE
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        matched = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                matched = key
        if matched is not None:
            seen.add(matched)
            out.append(f"{matched}={updates[matched]}")
            continue
        out.append(line)
    appended = [f"{k}={v}" for k, v in updates.items() if k not in seen]
    if appended:
        if out and out[-1].strip() != "":
            out.append("")
        out.append("# ---- Showly 云端模型订阅（一键启用写入）----")
        out.extend(appended)
    temp = path.with_suffix(".env.tmp")
    temp.write_text("\n".join(out) + "\n", encoding="utf-8")
    temp.replace(path)


def base_url(env_file: Path | None = None) -> str:
    override = _read_env(env_file).get(SUBSCRIPTION_BASE_ENV, "").strip().rstrip("/")
    return override or SUBSCRIPTION_BASE_URL


def get_subscription_key(env_file: Path | None = None) -> str:
    return _read_env(env_file).get(SUBSCRIPTION_KEY_ENV, "").strip()


def is_enabled(env_file: Path | None = None) -> bool:
    """已启用 = 直连三件套指向订阅端点且 Key 存在。"""
    env = _read_env(env_file)
    return (env.get("EASEL_DIRECT_API_BASE_URL", "").strip().rstrip("/") == base_url(env_file)
            and bool(env.get("EASEL_DIRECT_API_KEY", "").strip())
            and env.get("EASEL_CHAT_TRANSPORT", "").strip().lower() == "api")


def fetch_models(key: str, *, url: str | None = None, timeout: float = 15.0) -> list[str]:
    """GET {base}/models 拉模型清单（OpenAI 形状 {"data":[{"id":...}]}）。

    必须带自定义 UA：服务的网关拦截 Python-urllib 默认 User-Agent（403）。
    """
    target = (url or base_url()).rstrip("/") + "/models"
    request = urllib.request.Request(
        target,
        headers={"Authorization": f"Bearer {key}", "User-Agent": "Showly/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    items = payload.get("data") or payload.get("models") or [] if isinstance(payload, dict) else payload
    ids = []
    for item in items:
        model_id = item.get("id") if isinstance(item, dict) else item
        if isinstance(model_id, str) and model_id.strip():
            ids.append(model_id.strip())
    return sorted(set(ids))


def _pick(models: list[str], preferences: tuple[str, ...]) -> str | None:
    available = set(models)
    for name in preferences:
        if name in available:
            return name
    return None


def probe(key: str, *, timeout: float = 15.0, env_file: Path | None = None) -> list[str]:
    """验证 Key 并返回模型清单；失败抛 SubscriptionError（消息可展示）。"""
    if not key:
        raise SubscriptionError("缺少订阅 Key")
    if any(ch.isspace() for ch in key):
        raise SubscriptionError("订阅 Key 不能包含空白字符")
    try:
        return fetch_models(key, url=base_url(env_file), timeout=timeout)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise SubscriptionError("订阅 Key 无效或已失效，请检查后重试") from None
        raise SubscriptionError(f"订阅服务返回 HTTP {error.code}，请稍后重试") from None
    except urllib.error.URLError as error:
        raise SubscriptionError(f"无法连接订阅服务：{error.reason}") from None
    except (TimeoutError, OSError) as error:
        raise SubscriptionError(f"连接订阅服务超时或失败：{error}") from None
    except (json.JSONDecodeError, ValueError):
        raise SubscriptionError("订阅服务返回了无法解析的模型清单") from None


def enable(key: str | None = None, *, env_file: Path | None = None,
           timeout: float = 20.0, write: bool = True) -> dict:
    """一键启用：Key 解析（入参 > .env）→ 探测 → 全通道写入 → 逐通道报告。

    写入的通道：对话（直连）、生图、视频、音乐；语音/转写保持本地免费方案。
    生图/视频只在服务模型清单里出现对应模型时写默认值，缺失不阻断（标记 skipped）。
    """
    resolved = (key or "").strip() or get_subscription_key(env_file)
    key_source = "provided" if (key or "").strip() else "env"
    if not resolved:
        raise SubscriptionError(
            "没有可用的订阅 Key：请在输入框粘贴，或在 .env 里配置 EASEL_SUBSCRIPTION_KEY")

    models = probe(resolved, timeout=timeout, env_file=env_file)
    chat_model = _pick(models, CHAT_MODEL_PREFERENCES) or CHAT_MODEL_PREFERENCES[0]
    image_model = _pick(models, IMAGE_MODEL_PREFERENCES)
    video_model = _pick(models, VIDEO_MODEL_PREFERENCES)
    endpoint = base_url(env_file)

    updates: dict[str, str] = {
        SUBSCRIPTION_KEY_ENV: resolved,
        "EASEL_CHAT_TRANSPORT": "api",
        "EASEL_DIRECT_API_BASE_URL": endpoint,
        "EASEL_DIRECT_API_MODEL": chat_model,
        "EASEL_DIRECT_API_KEY": resolved,
    }
    image_channel = {"configured": bool(image_model), "model": image_model or "",
                     "status": "listed" if image_model else "skipped",
                     "note": "" if image_model else "服务模型清单中没有生图模型（gpt-image-*）"}
    if image_model:
        updates.update({
            "IMG_API_KEY": resolved,
            "IMG_BASE_URL": endpoint,
            "IMG_MODEL": image_model,
        })

    video_channel = {"configured": bool(video_model), "model": video_model or "",
                     "status": "listed" if video_model else "skipped",
                     "note": "" if video_model else "服务模型清单中没有视频模型（sora-2）"}
    if video_model:
        updates.update({
            "VIDEO_PROVIDER": "openai-compatible",
            "VIDEO_API_KEY": resolved,
            "VIDEO_BASE_URL": endpoint,
            "VIDEO_MODEL": video_model,
        })

    # Suno 协议不走 /models，无法免费探测；写入后标记未验证，失败不影响其他通道
    music_channel = {"configured": True, "model": MUSIC_MODEL_DEFAULT,
                     "status": "unverified",
                     "note": "Suno 协议无法自动验证；如生成失败请在高级配置中调整"}
    updates.update({
        "MUSIC_PROVIDER": "suno-compatible",
        "MUSIC_API_KEY": resolved,
        "MUSIC_BASE_URL": endpoint.rsplit("/v1", 1)[0],
        "MUSIC_MODEL": MUSIC_MODEL_DEFAULT,
    })

    if write:
        write_env(updates, env_file)

    return {
        "ok": True,
        "keySource": key_source,
        "baseUrl": endpoint,
        "chat": {"configured": True, "model": chat_model, "status": "verified"},
        "image": image_channel,
        "video": video_channel,
        "music": music_channel,
        "voice": {"configured": False, "model": "",
                  "status": "local",
                  "note": "本地 edge-tts 免费可用，零配置"},
        "transcribe": {"configured": False, "model": "",
                       "status": "local",
                       "note": "本地 faster-whisper 可用（首次使用自动下载模型）"},
        "modelCount": len(models),
    }


def status(env_file: Path | None = None) -> dict:
    """当前订阅状态（不探测网络）：供 GET 端点快速返回。"""
    env = _read_env(env_file)
    key = env.get(SUBSCRIPTION_KEY_ENV, "").strip()
    return {
        "keyPresent": bool(key),
        "enabled": is_enabled(env_file),
        "baseUrl": base_url(env_file),
        "chatModel": env.get("EASEL_DIRECT_API_MODEL", "").strip(),
        "imageModel": env.get("IMG_MODEL", "").strip(),
        "videoModel": env.get("VIDEO_MODEL", "").strip(),
        "musicModel": env.get("MUSIC_MODEL", "").strip(),
    }
