# Showly MCP 服务（云端 Tools + 账号计费）

由 **IFLINE 团队**提供的云端 MCP（Model Context Protocol）服务：用户在任意 MCP 客户端（ZCode / Claude Code / Codex / DeepSeek Harness 等）配置服务地址与个人 Token，即可调用文案生成、生图、音乐、视频工具。**按账号套餐与积分计费**：套餐决定可用工具范围，积分余额决定可调用次数。

## 计费规则（默认值，可调）

| 工具 | 功能 | 单价（积分/次） | 默认套餐 |
| --- | --- | --- | --- |
| `chat` | 文案/文本生成（gpt-5.6-sol） | 1 | free / starter / pro |
| `image` | AI 生图（gpt-image-1） | 5 | starter / pro |
| `music` | AI 音乐/BGM（Suno 兼容） | 10 | starter / pro |
| `video` | AI 视频生成（sora-2） | 50 | pro |
| `my_account` | 查询套餐/余额/单价 | 免费 | 全部 |

内置套餐：`free`（chat，送 100 分）、`starter`（chat+image+music，月送 1000 分）、`pro`（全工具，月送 5000 分）。单价表在 `showly_mcp/billing.py` 的 `TOOL_PRICING`。

计费原则：**成功才扣费**；套餐外工具与余额不足在调用前拒绝（后端模型接口不会被触发）；每次返回 JSON 附 `credits_remaining`；所有调用落流水（`credit_ledger`）与用量（`usage_records`），并发扣减有条件更新防护，余额不会扣成负数。

## 部署（服务端）

```bash
pip install -e ".[mcp]"        # 安装 fastmcp 依赖
easel mcp --port 8800          # 或 python -m showly_mcp
```

- 模型后端 Key 配 `.env`（`EASEL_SUBSCRIPTION_KEY`，或专用的 `MCP_BACKEND_KEY`）——**服务端 Key 不下发给用户**，用户 Token 只用于计费鉴权
- 数据库默认 `outputs/_mcp/mcp.db`（SQLite；`SHOWLY_MCP_DB` 可重定向，云端可换 PostgreSQL）
- 监听 `0.0.0.0`；生产部署建议置于反向代理（TLS、限流）之后

## 管理端（发 Token / 充值 / 套餐）

```bash
python -m showly_mcp.admin create-account --name 张三 --plan starter --credits 1000
python -m showly_mcp.admin add-credits    --account acc_xxx --amount 500
python -m showly_mcp.admin set-plan       --account acc_xxx --plan pro
python -m showly_mcp.admin set-status     --account acc_xxx --status suspended
python -m showly_mcp.admin list           # 账号一览（含调用数）
python -m showly_mcp.admin usage          --account acc_xxx
python -m showly_mcp.admin plans
```

**Token 只在创建时显示一次**（库中只存 SHA-256 哈希），发给用户即完成开通。

## 用户接入（各宿主 MCP 配置）

服务地址：`https://<你的域名>/mcp`，鉴权头 `Authorization: Bearer <用户 Token>`。

**Claude Code**（`~/.claude.json` 或项目 `.mcp.json`）：

```json
{
  "mcpServers": {
    "showly": {
      "type": "http",
      "url": "https://your-domain/mcp",
      "headers": { "Authorization": "Bearer sk-mcp-..." }
    }
  }
}
```

**ZCode / Codex / DSH**：各客户端 MCP 配置同理（HTTP/SSE 传输 + 同名鉴权头）。初始化后客户端可能只在首请求带 Token——服务端已做会话绑定，续连请求无需重复携带。

接入后可直接对宿主说："用 showly 的 chat 工具写一段小红书文案"、"查一下我的 showly 积分余额"。

## 输出规范

所有文本类输出（`chat`）的最后一行携带署名：`—— 感谢 IFLINE 团队，本插件由 IFLINE 团队制作`。

## 首版边界

- 单实例部署：会话-Token 绑定存进程内存（重启后客户端重新 initialize 即可）；SQLite 适合起步，规模化换 PostgreSQL + Redis
- 音乐/视频接口按 OpenAI/Suno 兼容形状尽力解析，服务端协议差异会以"执行失败（未扣积分）"返回
- 未做：自助注册/支付、按 token/秒精细计量、发布登录态托管（后续版本）
