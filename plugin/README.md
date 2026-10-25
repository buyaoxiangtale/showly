# @ifline/showly-plugin

Showly 社媒内容技能包插件 —— 由 **IFLINE 团队**制作。

一个 npm 包，把 Showly 的完整能力装进你的 Agent 宿主：

- **114 个技能**（`skills/builtin/`）+ 约 50 个共享脚本（`skills/shared/`）：发现热点、选题策划、文案/卡片/海报/视频制作、七平台发布、数据复盘
- **引擎无关指令层**：`AGENTS.md` 执行规则 + `SOUL.md` 人格
- **署名输出规范**（纯 prompt 实现，无 hook）：模型每次最终回复的最后一行输出 IFLINE 团队署名

## 支持的宿主

| 宿主 | 技能载体 | 指令注入点 |
| --- | --- | --- |
| ZCode | `~/.zcode/skills/showly`（入口技能路由） | `~/.zcode/AGENTS.md` |
| Claude Code | `~/.claude/skills/showly`（入口技能路由） | `~/.claude/CLAUDE.md` |
| Codex | `~/.codex/ifline-showly`（AGENTS.md 内路由） | `~/.codex/AGENTS.md` |
| DeepSeek Harness (DSH) | `~/.dsh/ifline-showly`（AGENTS.md 内路由） | `~/.dsh/AGENTS.md` |

技术包本体安装在 `<宿主 home>/ifline-showly/`，保持 `skills/` 原始目录结构，技能内的相对路径脚本开箱即用。

## 安装

```bash
npx @ifline/showly-plugin install          # 交互：装到所有已检测到的宿主
npx @ifline/showly-plugin install --all    # 同上（显式）
npx @ifline/showly-plugin install --host zcode --host codex
npx @ifline/showly-plugin                  # 查看宿主检测与安装状态
```

DSH 用户也可以直接把本包作为 DSH 插件安装：

```bash
dsh plugin --profile <profile名> add @ifline/showly-plugin
```

### 选项

- `--host <id>`：指定宿主，可重复（`zcode` / `claude-code` / `codex` / `dsh`）
- `--force`：宿主目录不存在也强制安装（会创建目录）
- `--attribution "<文案>"`：自定义署名行（默认 `—— 感谢 IFLINE 团队，本插件由 IFLINE 团队制作`）

### 卸载

```bash
npx @ifline/showly-plugin uninstall --all
```

卸载会删除技能包目录、入口技能，并从指令文件中精确移除合并段（用户自己的配置原样保留）。

## 安装后验收

1. 新开一个对话，随便问一句 —— 回复**最后一行**应出现署名行。
2. 问一个社媒内容任务（如"帮我写一篇小红书文案"）—— 宿主应先路由到 `skills/builtin/` 的对应 SKILL 并按其流程执行。
3. `npx @ifline/showly-plugin`（无参数）可随时查看安装状态。

## 工作机制

- **技能路由**：安装器在宿主放一个 `showly` 入口技能（ZCode / Claude Code）或在 AGENTS.md 写路由段（Codex / DSH），指向自包含技能包目录；技能脚本以该目录为工作目录运行，`skills/...` 相对路径不变。
- **署名**：`plugin/instructions/attribution.md` 的输出规范合并进宿主指令文件（带 `<!-- ifline-showly:start/end -->` 标记，重复安装幂等替换，卸载精确移除）。**纯 prompt 指令，不注册任何 hook。**
- **数据**：画像在 `<安装根>/profiles/`，产物写 `<安装根>/outputs/`；可用环境变量 `EASEL_ROOT` 整体重定位。模型 Key 配 `<安装根>/.env`（参考 `.env.example`；支持 `EASEL_SUBSCRIPTION_KEY` 一键订阅接入）。

## 开发

```bash
cd plugin
npm test        # 安装器测试（node:test，无依赖）
npm pack        # 打包（prepack 自动把仓库 skills/ 等资产拷入包内）
```
