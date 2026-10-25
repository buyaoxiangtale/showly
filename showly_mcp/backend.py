"""模型后端调用：复用订阅端点（api.openai-next.com/v1），服务端 Key 出 .env。

用户 MCP Token 只用于计费鉴权；模型服务 Key 永不下发给用户。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

# 与 easel/subscription.py 保持一致的端点与 UA 约定
DEFAULT_BASE_URL = "https://api.openai-next.com/v1"
USER_AGENT = "Showly-MCP/1.0"
TIMEOUT = 300.0

DEFAULT_MODELS = {
    "chat": "gpt-5.6-sol",
    "image": "gpt-image-1",
    "video": "sora-2",
    "music": "chirp-v5",
}


class BackendError(RuntimeError):
    """模型后端调用失败，消息可直接展示给用户。"""


def _read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def backend_key() -> str:
    """服务端模型 Key：.env 的订阅 Key（EASEL_SUBSCRIPTION_KEY）或专用 MCP_BACKEND_KEY。"""
    env = _read_env()
    key = env.get("MCP_BACKEND_KEY", "").strip() or env.get("EASEL_SUBSCRIPTION_KEY", "").strip()
    if not key:
        raise BackendError("服务端未配置模型 Key（.env 的 EASEL_SUBSCRIPTION_KEY），请联系管理员")
    return key


def base_url() -> str:
    env = _read_env()
    return env.get("EASEL_SUBSCRIPTION_BASE_URL", "").strip().rstrip("/") or DEFAULT_BASE_URL


def _post(path: str, payload: dict, *, timeout: float = TIMEOUT) -> dict:
    url = base_url() + path
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {backend_key()}",
                 "Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        raise BackendError(f"模型服务返回 HTTP {error.code}：{detail or error.reason}") from None
    except urllib.error.URLError as error:
        raise BackendError(f"无法连接模型服务：{error.reason}") from None
    except json.JSONDecodeError:
        raise BackendError("模型服务返回了无法解析的内容") from None


def chat(prompt: str, *, system: str | None = None, model: str | None = None) -> str:
    """文本生成（OpenAI 兼容 chat/completions，非流式）。"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    data = _post("/chat/completions", {
        "model": model or DEFAULT_MODELS["chat"], "messages": messages, "stream": False,
    })
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise BackendError("模型服务未返回对话内容") from None


def image(prompt: str, *, size: str = "1024x1024", model: str | None = None) -> dict:
    """生图（OpenAI 兼容 images/generations）。返回 url/b64 摘要。"""
    data = _post("/images/generations", {
        "model": model or DEFAULT_MODELS["image"], "prompt": prompt, "size": size, "n": 1,
    })
    try:
        item = data["data"][0]
    except (KeyError, IndexError, TypeError):
        raise BackendError("模型服务未返回图片") from None
    if item.get("url"):
        return {"image_url": item["url"]}
    if item.get("b64_json"):
        return {"image_b64_length": len(item["b64_json"]), "image_b64": item["b64_json"]}
    raise BackendError("模型服务返回的图片缺少 url/b64 数据")


def video(prompt: str, *, seconds: int = 8, model: str | None = None) -> dict:
    """生视频（OpenAI 兼容 /videos，同步等待或返回任务句柄由服务决定；按响应形状归一）。"""
    data = _post("/videos", {
        "model": model or DEFAULT_MODELS["video"], "prompt": prompt,
        "seconds": seconds,
    }, timeout=TIMEOUT)
    # 兼容两种返回：直接成片 {url} 或任务 {id,status}
    if isinstance(data, dict):
        if data.get("url"):
            return {"video_url": data["url"]}
        if data.get("id"):
            return {"job_id": data["id"], "status": data.get("status", "processing"),
                    "note": "视频生成中，请稍后用返回的 job_id 查询（或联系管理员）"}
    raise BackendError(f"模型服务返回了无法识别的视频响应：{str(data)[:120]}")


def music(prompt: str, *, model: str | None = None) -> dict:
    """音乐生成（Suno 兼容）。协议不统一，尽力解析常见形状；失败给可读错误。"""
    data = _post("/api/generate", {
        "model": model or DEFAULT_MODELS["music"], "prompt": prompt,
    })
    if isinstance(data, dict):
        clips = data.get("clips") or data.get("data") or []
        if isinstance(clips, list) and clips:
            first = clips[0]
            url = first.get("audio_url") or first.get("url") if isinstance(first, dict) else None
            if url:
                return {"audio_url": url}
        if data.get("id"):
            return {"job_id": data["id"], "status": data.get("status", "processing")}
    raise BackendError(f"音乐服务返回了无法识别的响应：{str(data)[:120]}")
