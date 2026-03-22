# 环境变量参考

ClawSentry 通过环境变量进行配置，遵循 12-Factor App 原则。本页列出所有支持的环境变量及其默认值。

---

## .env 文件支持

ClawSentry 在启动时会自动加载当前工作目录下的 `.env.clawsentry` 文件，无需手动 `source`。

!!! info "自动加载规则"
    - 文件名必须为 `.env.clawsentry`（不是 `.env`）
    - 仅当变量**尚未存在于环境中**时才加载（不覆盖已有值）
    - 支持 `#` 注释和引号包裹的值
    - 使用 Python 标准库实现，零外部依赖

```bash title=".env.clawsentry 示例"
# Gateway 核心配置
CS_HTTP_HOST=0.0.0.0
CS_HTTP_PORT=8080
CS_AUTH_TOKEN=my-secret-token

# LLM 配置
CS_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxx
CS_LLM_MODEL=gpt-4o
```

---

## Gateway 核心

控制 Gateway 服务的基本运行参数。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CS_HTTP_HOST` | `127.0.0.1` | HTTP 服务监听地址。设为 `0.0.0.0` 以接受外部连接 |
| `CS_HTTP_PORT` | `8080` | HTTP 服务端口 |
| `CS_AUTH_TOKEN` | (空=禁用认证) | Bearer Token 认证密钥。设置后所有 API 请求须携带 `Authorization: Bearer <token>` 头 |
| `CS_TRAJECTORY_DB_PATH` | `/tmp/clawsentry-trajectory.db` | SQLite 轨迹数据库路径。存储所有决策记录和审计轨迹 |
| `CS_UDS_PATH` | `/tmp/clawsentry.sock` | Unix Domain Socket 路径。主传输通道，延迟最低 |
| `CS_RATE_LIMIT_PER_MINUTE` | `300` | 每分钟最大请求数。设为 `0` 禁用速率限制。超限时返回 HTTP 429 |
| `AHP_TRAJECTORY_RETENTION_SECONDS` | `2592000` (30 天) | 轨迹数据保留时间（秒）。过期记录自动清理 |

!!! tip "生产环境建议"
    - 必须设置 `CS_AUTH_TOKEN` 以启用认证
    - 将 `CS_TRAJECTORY_DB_PATH` 指向持久化存储（非 `/tmp`）
    - UDS 文件会自动设置 `chmod 600` 权限，仅限属主进程访问

---

## LLM / 决策层

配置 L2 语义分析和 L3 审查 Agent 的 LLM 提供商。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CS_LLM_PROVIDER` | (空=仅规则引擎) | LLM 提供商。可选值：`anthropic`、`openai`、留空 |
| `CS_LLM_MODEL` | (provider 默认) | 覆盖默认模型名称。如 `claude-sonnet-4-20250514`、`gpt-4o` |
| `CS_LLM_BASE_URL` | (provider 默认) | OpenAI 兼容 API 基础 URL。用于自托管模型（Ollama、vLLM 等） |
| `CS_L3_ENABLED` | `false` | 启用 L3 审查 Agent。需要先配置 LLM provider。可选值：`true`/`1`/`yes` |
| `ANTHROPIC_API_KEY` | - | Anthropic API 密钥。`CS_LLM_PROVIDER=anthropic` 时必填 |
| `OPENAI_API_KEY` | - | OpenAI API 密钥。`CS_LLM_PROVIDER=openai` 时必填 |

!!! warning "API 密钥安全"
    API 密钥属于敏感信息，建议通过 `.env.clawsentry` 文件或密钥管理系统注入，切勿硬编码在脚本或版本控制中。

### 决策层级关系

```
CS_LLM_PROVIDER 未设置  →  仅 L1 规则引擎（零延迟，零成本）
CS_LLM_PROVIDER 已设置  →  L1 + L2 语义分析（CompositeAnalyzer）
CS_L3_ENABLED=true       →  L1 + L2 + L3 审查 Agent（完整三层）
```

---

## 会话执法

当单个会话累积多次高危决策时，自动触发强制措施。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AHP_SESSION_ENFORCEMENT_ENABLED` | `false` | 启用会话级强制策略。可选值：`true`/`1`/`yes` |
| `AHP_SESSION_ENFORCEMENT_THRESHOLD` | `3` | 触发强制措施的高危决策累积次数（最小值为 1） |
| `AHP_SESSION_ENFORCEMENT_ACTION` | `defer` | 强制措施类型。可选值见下表 |
| `AHP_SESSION_ENFORCEMENT_COOLDOWN_SECONDS` | `600` | 冷却期（秒）。到期后自动释放，允许会话恢复正常 |

**强制措施类型**

| 值 | 行为 |
|----|------|
| `defer` | 所有后续 `pre_action` 事件强制 DEFER，等待运维确认 |
| `block` | 所有后续 `pre_action` 事件直接 BLOCK |
| `l3_require` | 所有后续 `pre_action` 事件强制触发 L3 审查 Agent |

!!! example "配置示例"
    ```bash
    # 累积 5 次高危后阻断会话，冷却期 10 分钟
    AHP_SESSION_ENFORCEMENT_ENABLED=true
    AHP_SESSION_ENFORCEMENT_THRESHOLD=5
    AHP_SESSION_ENFORCEMENT_ACTION=block
    AHP_SESSION_ENFORCEMENT_COOLDOWN_SECONDS=600
    ```

---

## 安全

TLS 加密、Webhook 安全和 L3 Skills 扩展相关配置。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AHP_SSL_CERTFILE` | - | SSL/TLS 证书文件路径（PEM 格式） |
| `AHP_SSL_KEYFILE` | - | SSL/TLS 私钥文件路径（PEM 格式） |
| `AHP_WEBHOOK_IP_WHITELIST` | (空=不限制) | Webhook 来源 IP 白名单，逗号分隔。设置后仅允许列表内 IP 发送 Webhook |
| `AHP_WEBHOOK_TOKEN_TTL_SECONDS` | `86400` (24h) | Webhook Token 有效期（秒）。设为 `0` 禁用过期检查 |
| `AHP_SKILLS_DIR` | - | 自定义 L3 Skills YAML 目录路径。加载后与内置 Skills 合并 |
| `AHP_HTTP_URL` | (自动计算) | a3s-code HTTP Transport 目标 URL。默认基于 `CS_HTTP_HOST`/`CS_HTTP_PORT` 自动生成 |

!!! note "TLS 配置"
    同时设置 `AHP_SSL_CERTFILE` 和 `AHP_SSL_KEYFILE` 后，Gateway 将以 HTTPS 模式启动。
    ```bash
    AHP_SSL_CERTFILE=/etc/ssl/certs/clawsentry.pem
    AHP_SSL_KEYFILE=/etc/ssl/private/clawsentry-key.pem
    ```

!!! note "IP 白名单格式"
    ```bash
    # 允许特定 IP
    AHP_WEBHOOK_IP_WHITELIST=10.0.0.1,10.0.0.2,192.168.1.100
    ```

---

## OpenClaw 集成

连接 OpenClaw Gateway 实现实时审批执行。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENCLAW_WS_URL` | `ws://127.0.0.1:18789` | OpenClaw Gateway WebSocket URL |
| `OPENCLAW_OPERATOR_TOKEN` | - | OpenClaw 操作员认证 Token。在 `~/.openclaw/openclaw.json` 的 `gateway.auth.token` 中获取 |
| `OPENCLAW_ENFORCEMENT_ENABLED` | `false` | 启用 OpenClaw 审批执行（WS 监听 + 自动决策） |
| `OPENCLAW_WEBHOOK_HOST` | `127.0.0.1` | Webhook 接收器监听地址 |
| `OPENCLAW_WEBHOOK_PORT` | `8081` | Webhook 接收器端口 |
| `OPENCLAW_WEBHOOK_SECRET` | - | Webhook HMAC 签名密钥（用于验证请求完整性） |
| `OPENCLAW_WEBHOOK_TOKEN` | (内置默认) | Webhook Bearer Token（用于请求认证） |
| `OPENCLAW_MAPPING_GIT_SHA` | - | 归一化映射 Git SHA（事件归一化版本标识） |

### OpenClaw 自动检测

ClawSentry 会自动检测 OpenClaw 配置状态：

- 当 `OPENCLAW_WEBHOOK_TOKEN` 不等于内置默认值，或 `OPENCLAW_ENFORCEMENT_ENABLED=true` 时，自动启动 Webhook 接收器和 WS 事件监听
- 否则以 Gateway-only 模式运行

!!! warning "启用 Enforcement 前必读"
    设置 `OPENCLAW_ENFORCEMENT_ENABLED=true` 时，必须同时配置：

    - `OPENCLAW_OPERATOR_TOKEN` — 否则 WS 连接将失败
    - `OPENCLAW_WS_URL` — 必须以 `ws://` 或 `wss://` 开头

    启动时会执行预检验证，配置缺失将给出明确错误提示并退出。

---

## 完整配置示例

### 最小配置（仅 L1 规则引擎）

```bash title=".env.clawsentry"
# 无需任何配置，开箱即用
# 所有变量使用默认值
```

### 开发环境配置

```bash title=".env.clawsentry"
CS_HTTP_HOST=127.0.0.1
CS_HTTP_PORT=8080
CS_RATE_LIMIT_PER_MINUTE=0

# L2 语义分析
CS_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxx
CS_LLM_BASE_URL=http://localhost:11434/v1
CS_LLM_MODEL=qwen2.5:7b
```

### 生产环境配置

```bash title=".env.clawsentry"
# Gateway 核心
CS_HTTP_HOST=0.0.0.0
CS_HTTP_PORT=8080
CS_AUTH_TOKEN=prod-secret-token-xxxxx
CS_TRAJECTORY_DB_PATH=/var/lib/clawsentry/trajectory.db
CS_UDS_PATH=/var/run/clawsentry/gateway.sock
CS_RATE_LIMIT_PER_MINUTE=300

# TLS
AHP_SSL_CERTFILE=/etc/ssl/certs/clawsentry.pem
AHP_SSL_KEYFILE=/etc/ssl/private/clawsentry-key.pem

# 三层决策
CS_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxx
CS_L3_ENABLED=true

# 会话执法
AHP_SESSION_ENFORCEMENT_ENABLED=true
AHP_SESSION_ENFORCEMENT_THRESHOLD=3
AHP_SESSION_ENFORCEMENT_ACTION=defer
AHP_SESSION_ENFORCEMENT_COOLDOWN_SECONDS=600

# Webhook 安全
AHP_WEBHOOK_IP_WHITELIST=10.0.0.0/8
AHP_WEBHOOK_TOKEN_TTL_SECONDS=3600

# OpenClaw 集成
OPENCLAW_ENFORCEMENT_ENABLED=true
OPENCLAW_OPERATOR_TOKEN=your-openclaw-token
OPENCLAW_WS_URL=ws://127.0.0.1:18789
OPENCLAW_WEBHOOK_SECRET=your-hmac-secret
```

---

## 环境变量优先级

```
命令行参数 > 已存在的环境变量 > .env.clawsentry 文件 > 代码默认值
```

!!! tip "调试技巧"
    启动 Gateway 时，日志会输出已加载的环境变量数量：
    ```
    INFO [clawsentry.cli.dotenv_loader] Loaded 8 env vars from /path/to/.env.clawsentry
    ```
    如果某个变量未生效，检查是否已在系统环境中设置了同名变量（`.env.clawsentry` 不会覆盖已有值）。
