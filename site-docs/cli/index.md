---
title: CLI 命令参考
description: ClawSentry 全部命令行工具的完整使用手册
---

# CLI 命令参考

ClawSentry 提供统一的命令行入口 `clawsentry`，通过子命令完成框架初始化、网关启动、事件监控等操作。

## 调用方式

安装后，以下三种方式等价：

```bash
# 推荐方式
clawsentry <subcommand> [options]

# Python 模块调用
python -m clawsentry <subcommand> [options]

# 直接调用入口脚本（由 pip install 注册）
clawsentry-gateway   # 等价于 clawsentry gateway
clawsentry-harness   # 等价于 clawsentry harness
clawsentry-stack     # 等价于 clawsentry stack
```

!!! info "`.env.clawsentry` 自动加载"
    `clawsentry gateway`、`clawsentry stack`、`clawsentry start` 和 `clawsentry-gateway`、`clawsentry-stack` 启动时会自动读取当前目录下的 `.env.clawsentry` 文件，并将其中的环境变量注入进程。**已存在的环境变量不会被覆盖。**

    文件格式：
    ```ini
    # 注释行
    CS_AUTH_TOKEN=my-secret-token
    CS_HTTP_PORT=9100
    OPENCLAW_OPERATOR_TOKEN="quoted-value"
    ```

---

## clawsentry start

**一键启动 ClawSentry 监督网关**（推荐方式）。自动检测框架、初始化配置、启动 Gateway 并显示实时监控。

### 语法

```bash
clawsentry start [--framework {openclaw,a3s-code}] [--host HOST] [--port PORT]
                 [--no-watch] [--interactive | -i]
```

### 选项

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--framework` | 自动检测 | 目标框架：`openclaw` 或 `a3s-code` |
| `--host` | `127.0.0.1` | Gateway HTTP 监听地址 |
| `--port` | `8080` 或 `CS_HTTP_PORT` | Gateway HTTP 监听端口 |
| `--no-watch` | `false` | 仅启动 Gateway，不显示实时监控 |
| `--interactive` / `-i` | `false` | 启用 DEFER 决策交互式审批 |

### 工作流程

`clawsentry start` 会自动执行以下步骤：

1. **框架检测**：扫描 `~/.openclaw/openclaw.json` 或 `a3s-code` 配置文件，自动识别框架类型
2. **配置初始化**：如果 `.env.clawsentry` 不存在，自动运行 `clawsentry init <framework>`
3. **环境加载**：读取 `.env.clawsentry` 并注入环境变量
4. **Gateway 启动**：后台启动 Gateway 进程，等待健康检查通过
5. **实时监控**：前台显示 `clawsentry watch` 输出（除非使用 `--no-watch`）
6. **优雅关闭**：按 `Ctrl+C` 时，先发送 SIGTERM，5 秒后降级为 SIGKILL

### 示例

#### 自动检测并启动

```bash
clawsentry start
```

??? example "终端输出"
    ```
    [clawsentry] Detected framework: openclaw
    [clawsentry] Configuration already initialized
    [clawsentry] Starting gateway on 127.0.0.1:8080...
    INFO:     ahp-stack: === ClawSentry Supervision Gateway ===
    INFO:     ahp-stack: HTTP      : 127.0.0.1:8080
    INFO:     ahp-stack: OpenClaw  : WS ws://127.0.0.1:18789
    INFO:     openclaw-ws: Connected to OpenClaw Gateway

    Web UI: http://127.0.0.1:8080/ui?token=xK7m9p2QaB3...

    ──────────────────────────────────────────────────────────────
    [14:23:05] DECISION  session=my-session
      verdict : ALLOW
      risk    : low
      command : cat README.md
    ──────────────────────────────────────────────────────────────
    ```

#### 指定框架和端口

```bash
clawsentry start --framework a3s-code --port 9100
```

#### 仅启动 Gateway（不显示监控）

```bash
clawsentry start --no-watch
```

此模式下，Gateway 在后台运行，命令立即返回。你可以稍后手动运行 `clawsentry watch` 查看事件。

#### 启用交互式 DEFER 审批

```bash
clawsentry start --interactive
```

当收到 DEFER 决策时，终端会提示你输入 `[A]llow`、`[D]eny` 或 `[S]kip`。

### Web UI 自动登录

启动时，终端会显示带 token 的 Web UI URL：

```
Web UI: http://127.0.0.1:8080/ui?token=xK7m9p2QaB3...
```

点击该 URL 即可自动登录，无需手动输入 token。

### 错误处理

- **框架检测失败**：如果无法自动检测框架，命令会报错并提示使用 `--framework` 参数
- **初始化失败**：如果 `clawsentry init` 失败（如权限问题），命令会抛出 `RuntimeError`
- **Gateway 启动失败**：如果 Gateway 进程在 0.1 秒内退出，命令会报错并显示日志路径
- **健康检查超时**：如果 5 秒内 Gateway 未响应健康检查，命令会报错

### 日志位置

Gateway 的 stdout/stderr 输出会写入临时日志文件：

```
/tmp/clawsentry-gateway-<timestamp>.log
```

如果启动失败，命令会提示查看该日志文件。

---

## clawsentry init

初始化框架集成配置。根据目标框架生成 `.env` 配置文件和所需的设置文件。

### 语法

```bash
clawsentry init <framework> [--dir PATH] [--force] [--auto-detect] [--setup] [--dry-run]
```

### 参数

| 参数 | 说明 |
|------|------|
| `framework` | 目标框架，可选值：`a3s-code`、`openclaw` |

### 选项

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--dir PATH` | `.`（当前目录） | 配置文件写入目录 |
| `--force` | `false` | 覆盖已存在的配置文件 |
| `--auto-detect` | `false` | 自动检测已有的框架配置（如 `~/.openclaw/` 中的 Gateway Token） |
| `--setup` | `false` | 自动配置 OpenClaw 设置以支持 Monitor 集成（隐含 `--auto-detect`） |
| `--dry-run` | `false` | 预览 `--setup` 将要执行的 OpenClaw 配置变更，但不实际应用 |

### 示例

#### 初始化 a3s-code 集成

```bash
clawsentry init a3s-code
```

??? example "终端输出"
    ```
    [clawsentry] a3s-code integration initialized

      Files created:
        .env

      Environment variables:
        CS_UDS_PATH=/tmp/clawsentry.sock
        CS_AUTH_TOKEN=xK7m9p2QaB3...（自动生成 32 字符令牌）

      Next steps:
        1. source .env
        2. clawsentry gateway    # starts on UDS + HTTP port 8080
        3. Configure a3s-code AHP transport:
          program: "clawsentry-harness"
        4. clawsentry watch    # real-time terminal monitoring (port 8080)
    ```

#### 初始化 OpenClaw 集成（自动检测令牌）

```bash
clawsentry init openclaw --auto-detect
```

此命令会从 `~/.openclaw/openclaw.json` 中读取 `gateway.auth.token`，并自动填入 `.env` 文件。

#### 自动配置 OpenClaw + 预览变更

```bash
clawsentry init openclaw --setup --dry-run
```

??? example "终端输出"
    ```
    [clawsentry] openclaw integration initialized

      Files created:
        .env

      Environment variables:
        OPENCLAW_WS_URL=ws://127.0.0.1:18789
        OPENCLAW_OPERATOR_TOKEN=xxxxxxxxxxxxxxxx...
        CS_AUTH_TOKEN=xK7m9p2QaB3...

      Next steps:
        1. source .env
        2. clawsentry gateway
        3. clawsentry watch

      [DRY RUN] The following changes would be applied:
        - Set tools.exec.host = "gateway" in openclaw.json
        - Set exec-approvals security = "allowlist", ask = "always"
    ```

`--setup` 会自动配置以下 OpenClaw 关键设置：

- `tools.exec.host = "gateway"` —— 启用 Gateway 审批流程（默认 `sandbox` 跳过审批）
- `exec-approvals.json` —— 设置 `security: "allowlist"`, `ask: "always"`

!!! warning "备份机制"
    `--setup`（不带 `--dry-run`）会在修改前自动创建 `.bak` 备份文件。

---

## clawsentry gateway

启动 Supervision Gateway（监督网关）。自动检测 OpenClaw 配置，按需启用 Webhook/WebSocket 组件。

### 语法

```bash
clawsentry gateway [--gateway-host HOST] [--gateway-port PORT] [--uds-path PATH]
                    [--trajectory-db-path PATH] [--trajectory-retention-seconds N]
                    [--webhook-host HOST] [--webhook-port PORT]
                    [--webhook-token TOKEN] [--webhook-secret SECRET]
                    [--gateway-transport-preference PREF]
```

此命令委托给 `clawsentry.gateway.stack:main()`，等价于 `clawsentry stack`。

### 选项

#### 网关核心

| 选项 | 环境变量 | 默认值 | 说明 |
|------|----------|--------|------|
| `--gateway-host` | `CS_HTTP_HOST` | `127.0.0.1` | HTTP 服务监听地址 |
| `--gateway-port` | `CS_HTTP_PORT` | `8080` | HTTP 服务监听端口 |
| `--uds-path` | `CS_UDS_PATH` | `/tmp/clawsentry.sock` | Unix Domain Socket 路径 |
| `--trajectory-db-path` | `CS_TRAJECTORY_DB_PATH` | `/tmp/clawsentry-trajectory.db` | 轨迹数据库路径（SQLite） |
| `--trajectory-retention-seconds` | `AHP_TRAJECTORY_RETENTION_SECONDS` | `2592000`（30 天） | 轨迹记录保留时间 |

#### OpenClaw Webhook

| 选项 | 环境变量 | 默认值 | 说明 |
|------|----------|--------|------|
| `--webhook-host` | `OPENCLAW_WEBHOOK_HOST` | `127.0.0.1` | Webhook 接收器监听地址 |
| `--webhook-port` | `OPENCLAW_WEBHOOK_PORT` | `8081` | Webhook 接收器监听端口 |
| `--webhook-token` | `OPENCLAW_WEBHOOK_TOKEN` | （内置默认值） | Webhook 认证令牌 |
| `--webhook-secret` | `OPENCLAW_WEBHOOK_SECRET` | `None` | HMAC 签名密钥 |
| `--webhook-require-https` | — | `false` | 要求 Webhook 使用 HTTPS（localhost 豁免） |
| `--webhook-max-body-bytes` | — | `1048576`（1 MB） | Webhook 请求体大小限制 |

#### 高级选项

| 选项 | 环境变量 | 默认值 | 说明 |
|------|----------|--------|------|
| `--gateway-transport-preference` | — | `uds_first` | OpenClaw Gateway 客户端传输顺序：`uds_first` 或 `http_first` |
| `--source-protocol-version` | — | （自动检测） | OpenClaw 协议版本 |
| `--git-short-sha` | — | （自动检测） | OpenClaw Git 版本标识 |
| `--profile-version` | — | `1` | 映射规则版本号 |

### 运行模式自动检测

Gateway 通过以下条件判断是否启用 OpenClaw 集成：

- `OPENCLAW_WEBHOOK_TOKEN` 不等于内置默认值，**或者**
- `OPENCLAW_ENFORCEMENT_ENABLED=true`

满足任一条件时，自动启动 Webhook 接收器和 WebSocket 事件监听。否则仅启动 Gateway 核心（UDS + HTTP）。

### 示例

#### 仅 Gateway 模式

```bash
clawsentry gateway
```

??? example "启动日志"
    ```
    2026-03-23T10:00:00 [ahp-stack] Gateway-only starting:
      gateway=http://127.0.0.1:8080/ahp
      uds=/tmp/clawsentry.sock
      (no OpenClaw config detected)
    ```

#### 完整模式（含 OpenClaw 集成）

```bash
export OPENCLAW_WEBHOOK_TOKEN=my-webhook-token
export OPENCLAW_ENFORCEMENT_ENABLED=true
export OPENCLAW_OPERATOR_TOKEN=xxxxxxxxxxxxxxxx...
export OPENCLAW_WS_URL=ws://127.0.0.1:18789

clawsentry gateway --gateway-port 9100 --webhook-port 9101
```

??? example "启动日志"
    ```
    2026-03-23T10:00:00 [ahp-stack] Full stack starting:
      gateway=http://127.0.0.1:9100/ahp
      uds=/tmp/clawsentry.sock
      webhook=http://127.0.0.1:9101/webhook/openclaw
    2026-03-23T10:00:00 [ahp-stack] OpenClaw WS enforcement listener active
    ```

#### 指定 SSL 证书启动

```bash
export AHP_SSL_CERTFILE=/etc/ssl/certs/clawsentry.pem
export AHP_SSL_KEYFILE=/etc/ssl/private/clawsentry-key.pem

clawsentry gateway
```

---

## clawsentry stack

`clawsentry gateway` 的别名。语法和选项完全相同。

```bash
clawsentry stack [options]
```

保留此命令是为了向后兼容早期版本。推荐使用 `clawsentry gateway`。

---

## clawsentry harness

启动 a3s-code stdio Harness（AHP 钩子进程）。该进程通过 stdin/stdout 与 a3s-code 通信，将 Hook 事件转发到 ClawSentry Gateway 进行安全评估。

### 语法

```bash
clawsentry harness [--uds-path PATH] [--default-deadline-ms MS]
                    [--max-rpc-retries N] [--retry-backoff-ms MS]
                    [--default-session-id ID] [--default-agent-id ID]
```

### 选项

| 选项 | 环境变量 | 默认值 | 说明 |
|------|----------|--------|------|
| `--uds-path` | `CS_UDS_PATH` | `/tmp/clawsentry.sock` | Gateway UDS 路径 |
| `--default-deadline-ms` | `A3S_GATEWAY_DEFAULT_DEADLINE_MS` | `100` | RPC 请求超时（毫秒） |
| `--max-rpc-retries` | `A3S_GATEWAY_MAX_RPC_RETRIES` | `1` | RPC 最大重试次数 |
| `--retry-backoff-ms` | `A3S_GATEWAY_RETRY_BACKOFF_MS` | `50` | 重试间隔退避（毫秒） |
| `--default-session-id` | `A3S_GATEWAY_DEFAULT_SESSION_ID` | `ahp-session` | 默认会话 ID |
| `--default-agent-id` | `A3S_GATEWAY_DEFAULT_AGENT_ID` | `ahp-agent` | 默认 Agent ID |

### 工作原理

1. 从 stdin 逐行读取 JSON-RPC 2.0 消息
2. 将 a3s-code Hook 事件归一化为 AHP `CanonicalEvent`
3. 通过 UDS 转发至 Gateway 获取决策
4. 将 `CanonicalDecision` 转换为 a3s-code 可识别的响应格式
5. 将响应写入 stdout

### 支持的 Hook 事件类型

| a3s-code Hook | AHP EventType | 阻塞 | 说明 |
|---------------|---------------|------|------|
| `PreToolUse` | `pre_action` | :material-check: | 工具调用前拦截 |
| `PostToolUse` | `post_action` | :material-close: | 工具调用后审计 |
| `PrePrompt` | `pre_prompt` | :material-check: | Prompt 发送前检查 |
| `GenerateStart` | `pre_prompt` | :material-check: | LLM 生成前检查 |
| `SessionStart` | `session` | :material-close: | 会话启动通知 |
| `SessionEnd` | `session` | :material-close: | 会话结束通知 |
| `OnError` | `error` | :material-close: | 错误事件审计 |

!!! note "未映射事件"
    `GenerateEnd`、`SkillLoad`、`SkillUnload` 事件不会被映射，Harness 会静默忽略。

### 本地降级

当 Gateway 不可达时（UDS 连接失败或超时），Harness 会自动执行本地降级决策：

- 包含 `destructive_pattern` 或 `shell_execution` 风险提示 → **BLOCK**
- 其他情况 → **ALLOW**（fail-open，低危场景）

### 示例

```bash
# 直接启动（通常由 a3s-code 自动调用）
clawsentry harness --uds-path /tmp/clawsentry.sock

# 手动测试：发送 handshake
echo '{"jsonrpc":"2.0","id":1,"method":"ahp/handshake","params":{}}' | clawsentry harness
```

??? example "Handshake 响应"
    ```json
    {
      "jsonrpc": "2.0",
      "id": 1,
      "result": {
        "protocol_version": "2.0",
        "harness_info": {
          "name": "a3s-gateway-harness",
          "version": "1.0.0",
          "capabilities": [
            "pre_action",
            "post_action",
            "pre_prompt",
            "session",
            "error"
          ]
        }
      }
    }
    ```

---

## clawsentry watch

实时监控 Gateway 的 SSE（Server-Sent Events）事件流，在终端以彩色格式化输出或原始 JSON 展示。

### 语法

```bash
clawsentry watch [--gateway-url URL] [--token TOKEN] [--filter TYPES]
                 [--json] [--no-color] [--interactive | -i]
```

### 选项

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--gateway-url URL` | `http://127.0.0.1:{CS_HTTP_PORT}` | Gateway 基础 URL |
| `--token TOKEN` | `None` | Bearer 认证令牌 |
| `--filter TYPES` | `None`（全部） | 逗号分隔的事件类型过滤器 |
| `--json` | `false` | 输出原始 JSON（适合管道处理） |
| `--no-color` | `false` | 禁用 ANSI 颜色代码 |
| `--interactive` / `-i` | `false` | DEFER 决策交互确认模式 |

### 支持的事件类型

用于 `--filter` 的可选值：

| 事件类型 | 说明 |
|----------|------|
| `decision` | 每次决策结果（ALLOW/BLOCK/DEFER/MODIFY） |
| `alert` | 高风险告警 |
| `session_start` | 新会话创建 |
| `session_risk_change` | 会话风险等级变更 |
| `session_enforcement_change` | 会话强制策略状态变更 |

### 终端输出格式

#### 决策事件

```
[10:30:45]  BLOCK     rm -rf /data                             risk=high    D1: destructive pattern
[10:30:46]  ALLOW     cat README.md                            risk=low
[10:30:47]  DEFER     sudo chmod 777 /etc/passwd               risk=high    Requires operator approval
```

颜色编码：:red_square: BLOCK (红色) | :green_square: ALLOW (绿色) | :yellow_square: DEFER (黄色) | :blue_square: MODIFY (青色)

#### 告警事件

```
[10:30:45]  ALERT     sess=sess-001  severity=high  Risk escalation detected
```

#### 会话事件

```
[10:30:45]  SESSION   started  sess=sess-001  agent=agent-1  framework=a3s-code
[10:31:00]  RISK      sess=sess-001  low -> high
```

### 交互模式

使用 `--interactive` 或 `-i` 启动交互模式。当收到 DEFER 决策时，运维人员可以实时做出允许或拒绝的决定：

```
  Command: sudo rm -rf /var/log
  Reason:  Destructive operation on system logs
  [A]llow  [D]eny  [S]kip (timeout in 25s) >
```

- 输入 `a` —— 允许执行（resolve 为 `allow-once`）
- 输入 `d` —— 拒绝执行（resolve 为 `deny`，附带原因 `operator denied via watch CLI`）
- 输入 `s` 或直接回车 —— 跳过不处理
- 超时未响应 —— 自动跳过（保留 5 秒安全余量防止竞态）

### 示例

#### 基础监控

```bash
clawsentry watch --token my-secret-token
```

#### 仅监控决策和告警

```bash
clawsentry watch --filter decision,alert --token my-secret-token
```

#### JSON 输出（适合管道）

```bash
clawsentry watch --json --token my-secret-token | jq '.decision'
```

#### 运维交互确认

```bash
clawsentry watch --interactive --token my-secret-token
```

### 连接行为

- 启动时显示 `Connected to <url>`
- 连接断开后自动重连（间隔 3 秒）
- `Ctrl+C` 优雅退出

---

## 独立入口点

以下命令由 `pip install clawsentry` 注册为独立可执行文件，无需使用 `clawsentry` 前缀：

| 命令 | 等价于 | 入口模块 |
|------|--------|----------|
| `clawsentry-gateway` | `clawsentry gateway` | `clawsentry.gateway.server:main` |
| `clawsentry-harness` | `clawsentry harness` | `clawsentry.adapters.a3s_gateway_harness:main` |
| `clawsentry-stack` | `clawsentry stack` | `clawsentry.gateway.stack:main` |

!!! tip "何时使用独立入口"
    在 a3s-code 的 Hook 配置中，直接指定 `clawsentry-harness` 作为程序路径更为简洁：
    ```hcl
    hooks {
      ahp {
        transport = "stdio"
        program   = "clawsentry-harness"
      }
    }
    ```

---

## 环境变量速查

以下环境变量影响 CLI 行为。完整列表参见 [环境变量配置](../configuration/env-vars.md)。

| 变量 | 影响的命令 | 说明 |
|------|-----------|------|
| `CS_AUTH_TOKEN` | gateway, watch | HTTP API 认证令牌 |
| `CS_HTTP_HOST` | gateway | HTTP 监听地址 |
| `CS_HTTP_PORT` | gateway, watch | HTTP 监听端口 |
| `CS_UDS_PATH` | gateway, harness | UDS Socket 路径 |
| `CS_TRAJECTORY_DB_PATH` | gateway | 轨迹数据库路径 |
| `CS_RATE_LIMIT_PER_MINUTE` | gateway | 每 IP 每分钟请求限额 |
| `OPENCLAW_WEBHOOK_TOKEN` | gateway | OpenClaw Webhook 令牌 |
| `OPENCLAW_ENFORCEMENT_ENABLED` | gateway | 启用 OpenClaw WS 强制执行 |
| `OPENCLAW_OPERATOR_TOKEN` | gateway | OpenClaw WS 操作令牌 |
| `OPENCLAW_WS_URL` | gateway | OpenClaw WebSocket URL |
| `AHP_SESSION_ENFORCEMENT_ENABLED` | gateway | 启用会话级强制策略 |
| `AHP_SSL_CERTFILE` | gateway | SSL 证书文件路径 |
| `AHP_SSL_KEYFILE` | gateway | SSL 私钥文件路径 |
