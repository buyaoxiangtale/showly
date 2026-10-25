"""Showly MCP 服务端（FastMCP，streamable-http）。

鉴权：HTTP 头 ``Authorization: Bearer sk-mcp-...``（账号 Token，区别于服务端模型 Key）。
计费：预检（套餐白名单 + 余额）→ 执行 → 成功扣积分、失败登记不扣费；
每个工具返回 JSON，附带 ``credits_remaining``。
署名：与插件一致的 IFLINE 团队署名规范写入 tool 描述与文本输出末行。

原始工具函数（``_chat_tool`` 等）不依赖请求上下文即可直接调用/测试；
``mcp.tool()`` 注册的是同一函数对象。
"""
from __future__ import annotations

import contextvars
import time

from fastmcp import FastMCP

from showly_mcp import backend, billing

ATTRIBUTION = "—— 感谢 IFLINE 团队，本插件由 IFLINE 团队制作"

# 请求级 Bearer Token：ASGI 中间件截获原始头写入（get_http_headers 在部分
# streamable 场景取不到，contextvar 在同请求的工具调用链内可靠传播）
_TOKEN_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("showly_token", default="")

mcp = FastMCP("Showly Tools", instructions=(
    "Showly 云端内容工具（IFLINE 团队）。按账号套餐与积分计费："
    "每次成功调用扣积分，失败不扣。工具返回 JSON 内含 credits_remaining。"
))


def _current_token() -> str:
    """当前请求的 Bearer Token（ASGI 中间件写入的 contextvar）。"""
    auth = _TOKEN_VAR.get()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _execute(tool: str, func):
    """共享执行链：鉴权 → 预检 → 执行 → 成功扣费/失败登记。返回 JSON dict。

    工具函数用显式签名调用本函数（FastMCP 依签名生成 schema，不支持 **kwargs）。
    """
    started = time.time()
    try:
        account = billing.authenticate(_current_token())
    except billing.AuthError as error:
        return {"error": f"鉴权失败：{error}"}
    try:
        price = billing.precheck(account, tool)
    except billing.QuotaError as error:
        return {"error": str(error), "credits_remaining": account["credits"],
                "plan": account["plan_name"]}
    try:
        payload = dict(func())
        credits_remaining = billing.charge(
            account["id"], tool, price, ok=True,
            elapsed_ms=int((time.time() - started) * 1000))
        payload["credits_remaining"] = credits_remaining
        payload["attribution"] = ATTRIBUTION
        return payload
    except backend.BackendError as error:
        billing.record_failure(account["id"], tool, str(error),
                               elapsed_ms=int((time.time() - started) * 1000))
        return {"error": f"执行失败（未扣积分）：{error}",
                "credits_remaining": account["credits"]}


async def _chat_tool(prompt: str, system: str = "") -> dict:
    return _execute("chat", lambda: {
        "text": backend.chat(prompt, system=system or None).rstrip()
                + "\n\n" + ATTRIBUTION})


async def _image_tool(prompt: str, size: str = "1024x1024") -> dict:
    return _execute("image", lambda: backend.image(prompt, size=size))


async def _music_tool(prompt: str) -> dict:
    return _execute("music", lambda: backend.music(prompt))


async def _video_tool(prompt: str, seconds: int = 8) -> dict:
    return _execute("video", lambda: backend.video(prompt, seconds=seconds))


async def _my_account_tool() -> dict:
    try:
        account = billing.authenticate(_current_token())
    except billing.AuthError as error:
        return {"error": f"鉴权失败：{error}"}
    return {
        "account": account["name"],
        "plan": account["plan_name"],
        "allowed_tools": account["allowed_tools"],
        "credits_remaining": account["credits"],
        "pricing": billing.TOOL_PRICING,
    }


_chat_tool.__doc__ = (
    "文本/文案生成（社媒文案、脚本、改写等）。计费：1 积分/次。\n\n"
    "返回 JSON：{text, credits_remaining, attribution}。文本末行含 IFLINE 团队署名。")
_image_tool.__doc__ = (
    "AI 生图（封面、卡片、海报等，OpenAI 兼容）。计费：5 积分/次。\n\n"
    "返回 JSON：{image_url 或 image_b64, credits_remaining}。")
_music_tool.__doc__ = (
    "AI 音乐/BGM 生成（Suno 兼容）。计费：10 积分/次。需要套餐包含 music。\n\n"
    "返回 JSON：{audio_url 或 job_id, credits_remaining}。")
_video_tool.__doc__ = (
    "AI 视频生成（sora-2，OpenAI 兼容 /videos）。计费：50 积分/次。需要 Pro 套餐。\n\n"
    "视频生成耗时较长；可能返回 job_id（异步任务）而非直接成片 URL。")
_my_account_tool.__doc__ = "查询当前账号：套餐、可用工具、积分余额、计费单价。"

chat = mcp.tool(name="chat")(_chat_tool)
image = mcp.tool(name="image")(_image_tool)
music = mcp.tool(name="music")(_music_tool)
video = mcp.tool(name="video")(_video_tool)
my_account = mcp.tool(name="my_account")(_my_account_tool)


class _BearerCaptureMiddleware:
    """ASGI 层鉴权头捕获 + 会话绑定。

    标准 streamable HTTP 客户端初始化后可能只带 Mcp-Session-Id 不再带
    Authorization，所以 initialize 请求（带 auth）时把 token 绑到该 session，
    后续同 session 请求自动复用。进程内 dict 足够（单实例部署）。
    """

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app
        self._session_tokens: dict[str, str] = {}

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.asgi_app(scope, receive, send)
            return
        headers = {name.decode("latin1").lower(): value.decode("latin1")
                   for name, value in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        session_req = headers.get("mcp-session-id", "")
        if auth:
            _TOKEN_VAR.set(auth)
            if session_req:
                self._session_tokens[session_req] = auth
        elif session_req and session_req in self._session_tokens:
            _TOKEN_VAR.set(self._session_tokens[session_req])

        async def send_wrapper(message):
            # initialize 响应会下发新 session id：把它与本次 auth 绑定
            if (auth and message.get("type") == "http.response.start"
                    and not session_req):
                for name, value in message.get("headers", []):
                    if name.decode("latin1").lower() == "mcp-session-id":
                        self._session_tokens[value.decode("latin1")] = auth
                        break
            await send(message)

        await self.asgi_app(scope, receive, send_wrapper)


def app():
    """FastMCP 的 streamable-http ASGI 应用（包 Bearer 捕获 + 会话绑定中间件）。"""
    return _BearerCaptureMiddleware(mcp.http_app(path="/mcp"))


def main(port: int = 8800) -> None:  # pragma: no cover - 启动入口
    import uvicorn
    print(f"\n  ✦ Showly MCP 服务")
    print(f"  http://localhost:{port}/mcp  (Bearer Token 鉴权)\n")
    uvicorn.run(app(), host="0.0.0.0", port=port, log_level="warning")
