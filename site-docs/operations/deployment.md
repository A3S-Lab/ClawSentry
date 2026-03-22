---
title: 生产部署
description: ClawSentry 生产环境部署指南，涵盖安全配置、SSL、系统服务和运维最佳实践
---

# 生产部署

本指南涵盖 ClawSentry 在生产环境中的部署配置。ClawSentry 设计为轻量级单进程服务，适合以 Sidecar 模式运行在 AI Agent 旁边。

---

## 单机部署

### 安装

```bash
pip install "clawsentry[llm]"
```

`[llm]` 可选依赖组包含 `anthropic` 和 `openai` SDK，如果你只需要 L1 规则引擎，可以省略：

```bash
pip install clawsentry
```

### 验证安装

```bash
clawsentry --version
clawsentry gateway --help
```

---

## systemd 服务配置

推荐使用 systemd 管理 ClawSentry Gateway 服务的生命周期。

### 服务单元文件

```ini title="/etc/systemd/system/clawsentry.service"
[Unit]
Description=ClawSentry AHP Supervision Gateway
Documentation=https://clawsentry.readthedocs.io
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=clawsentry
Group=clawsentry
EnvironmentFile=/etc/clawsentry/env
ExecStart=/usr/local/bin/clawsentry gateway
Restart=on-failure
RestartSec=5
StartLimitBurst=3
StartLimitIntervalSec=60

# 安全加固
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ReadWritePaths=/var/lib/clawsentry /tmp/clawsentry.sock

# 资源限制
LimitNOFILE=65536
MemoryMax=512M

[Install]
WantedBy=multi-user.target
```

### 创建系统用户

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin clawsentry
sudo mkdir -p /var/lib/clawsentry
sudo chown clawsentry:clawsentry /var/lib/clawsentry
```

### 启用并启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable clawsentry
sudo systemctl start clawsentry
sudo systemctl status clawsentry
```

---

## 环境变量配置

以下是生产环境推荐的完整环境变量配置文件：

```bash title="/etc/clawsentry/env"
# ===== 核心配置 =====
# 认证令牌（必须设置，生成方法见下文）
CS_AUTH_TOKEN=your-strong-token-here

# HTTP 服务器
CS_HTTP_HOST=127.0.0.1
CS_HTTP_PORT=8080

# UDS 路径
CS_UDS_PATH=/tmp/clawsentry.sock

# ===== 数据持久化 =====
# 轨迹数据库路径（SQLite）
CS_TRAJECTORY_DB_PATH=/var/lib/clawsentry/trajectory.db

# ===== LLM 配置（可选，启用 L2 LLM 分析） =====
CS_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
CS_LLM_MODEL=gpt-4

# 启用 L3 审查 Agent（可选）
CS_L3_ENABLED=false

# 自定义 L3 Skills 目录（可选）
# AHP_SKILLS_DIR=/etc/clawsentry/skills

# ===== SSL/TLS（推荐） =====
AHP_SSL_CERTFILE=/etc/clawsentry/ssl/cert.pem
AHP_SSL_KEYFILE=/etc/clawsentry/ssl/key.pem

# ===== 速率限制 =====
AHP_RATE_LIMIT_PER_MINUTE=300

# ===== Webhook 安全（如果使用 OpenClaw Webhook） =====
# AHP_WEBHOOK_IP_WHITELIST=127.0.0.1,10.0.0.0/8
# AHP_WEBHOOK_TOKEN_TTL_SECONDS=3600

# ===== 会话执法策略 =====
AHP_SESSION_ENFORCEMENT_ENABLED=true
AHP_SESSION_ENFORCEMENT_THRESHOLD=3
AHP_SESSION_ENFORCEMENT_ACTION=defer
AHP_SESSION_ENFORCEMENT_COOLDOWN_SECONDS=600

# ===== OpenClaw 集成（如果使用） =====
# OPENCLAW_WS_URL=ws://127.0.0.1:18789
# OPENCLAW_OPERATOR_TOKEN=your-openclaw-token
# OPENCLAW_ENFORCEMENT_ENABLED=true

# ===== dotenv 自动加载（可选） =====
# 如果使用 .env 文件，Gateway 会自动加载
```

---

## 认证配置

### 生成强认证令牌

```bash
# 使用 openssl 生成 32 字节随机令牌
openssl rand -hex 32
```

或使用 Python：

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

将生成的令牌设置为 `CS_AUTH_TOKEN` 环境变量。

!!! danger "生产环境必须启用认证"
    如果 `CS_AUTH_TOKEN` 为空或未设置，Gateway 的 HTTP API 将不进行认证检查。在生产环境中这是严重的安全风险。

### 认证方式

所有 HTTP API 请求需要在 Header 中携带 Bearer Token：

```
Authorization: Bearer <CS_AUTH_TOKEN>
```

SSE 连接使用 URL Query 参数：

```
/report/stream?token=<CS_AUTH_TOKEN>
```

---

## SSL/TLS 配置

生产环境强烈建议启用 HTTPS，特别是当 SSE 连接通过 URL 参数传递认证令牌时。

### 生成自签名证书（测试用）

```bash
sudo mkdir -p /etc/clawsentry/ssl

openssl req -x509 -newkey rsa:4096 \
  -keyout /etc/clawsentry/ssl/key.pem \
  -out /etc/clawsentry/ssl/cert.pem \
  -days 365 -nodes \
  -subj "/CN=clawsentry.local"

sudo chmod 600 /etc/clawsentry/ssl/key.pem
sudo chown clawsentry:clawsentry /etc/clawsentry/ssl/*.pem
```

### 使用 Let's Encrypt 证书

如果 Gateway 暴露在公网（不推荐，但某些场景需要）：

```bash
# 使用 certbot 获取证书
sudo certbot certonly --standalone -d your-domain.example.com

# 配置环境变量
AHP_SSL_CERTFILE=/etc/letsencrypt/live/your-domain.example.com/fullchain.pem
AHP_SSL_KEYFILE=/etc/letsencrypt/live/your-domain.example.com/privkey.pem
```

### 配置环境变量

```bash
AHP_SSL_CERTFILE=/etc/clawsentry/ssl/cert.pem
AHP_SSL_KEYFILE=/etc/clawsentry/ssl/key.pem
```

Gateway 启动时会自动检测这两个环境变量，如果都已设置则启用 HTTPS。

!!! note "UDS 通信不受 SSL 影响"
    Unix Domain Socket 通信不经过网络层，因此不需要 SSL。UDS 的安全性通过文件权限控制（`chmod 600`）。

---

## 数据库配置

ClawSentry 使用 SQLite 存储决策轨迹数据。

### 路径配置

```bash
CS_TRAJECTORY_DB_PATH=/var/lib/clawsentry/trajectory.db
```

默认路径为 `/tmp/clawsentry-trajectory.db`，生产环境应指向持久化存储。

### 数据保留

默认保留 30 天的轨迹数据。过期数据会在 Gateway 运行时定期清理。

### 备份策略

SQLite 数据库可以通过简单的文件复制进行备份：

```bash title="/etc/cron.daily/clawsentry-backup"
#!/bin/bash
# ClawSentry 轨迹数据库每日备份
BACKUP_DIR=/var/backups/clawsentry
DB_PATH=/var/lib/clawsentry/trajectory.db
DATE=$(date +%Y%m%d)

mkdir -p "$BACKUP_DIR"

# 使用 sqlite3 的 .backup 命令确保一致性
sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/trajectory-$DATE.db'"

# 保留最近 7 天的备份
find "$BACKUP_DIR" -name "trajectory-*.db" -mtime +7 -delete
```

```bash
sudo chmod +x /etc/cron.daily/clawsentry-backup
```

!!! tip "在线备份"
    使用 `sqlite3 .backup` 命令可以在 Gateway 运行时安全地进行备份，无需停止服务。

---

## 日志配置

ClawSentry 使用 Python 标准 `logging` 模块。生产环境建议配置结构化日志：

### 基础配置

```python title="logging_config.py"
import logging
import logging.handlers

# 配置根日志器
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 或使用文件日志 + 轮转
handler = logging.handlers.RotatingFileHandler(
    "/var/log/clawsentry/gateway.log",
    maxBytes=50 * 1024 * 1024,  # 50MB
    backupCount=5,
)
handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
logging.getLogger("clawsentry").addHandler(handler)
```

### 关键日志名称

| Logger 名称 | 用途 |
|-------------|------|
| `clawsentry` | Gateway 核心（决策、API 请求） |
| `a3s-adapter` | a3s-code 适配器 |
| `openclaw-adapter` | OpenClaw 适配器 |
| `ahp.review-skills` | L3 Skill 加载 |
| `ahp.llm-factory` | LLM 分析器构建 |

### systemd 日志查看

```bash
# 查看实时日志
sudo journalctl -u clawsentry -f

# 查看最近 100 行
sudo journalctl -u clawsentry -n 100

# 按时间范围过滤
sudo journalctl -u clawsentry --since "2026-03-23 10:00" --until "2026-03-23 11:00"
```

---

## 资源需求

ClawSentry 设计为轻量级单进程服务，资源需求很低。

### 最低要求

| 资源 | 最低 | 推荐 |
|------|------|------|
| CPU | 1 核 | 2 核 |
| 内存 | 128 MB | 256 MB |
| 磁盘 | 100 MB | 1 GB（含轨迹数据库） |
| Python | 3.10+ | 3.12+ |

### 性能参考

| 指标 | 典型值 |
|------|--------|
| L1 决策延迟 | < 1 ms |
| L2 规则分析延迟 | < 5 ms |
| L2 LLM 分析延迟 | 1-3 秒 |
| L3 Agent 审查延迟 | 5-30 秒 |
| 内存占用（基础） | ~50 MB |
| 内存占用（含 Web UI） | ~80 MB |
| SQLite 写入速率 | > 1000 records/sec |

!!! info "L2/L3 延迟取决于 LLM 提供商"
    L2 LLM 分析和 L3 Agent 审查的延迟主要取决于 LLM API 的响应速度。本地部署的小模型可以显著降低延迟。

---

## 健康检查

Gateway 提供 `GET /health` 端点用于健康检查：

```bash
curl http://localhost:8080/health
```

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

### systemd 健康检查

在服务单元文件中添加 Watchdog：

```ini
[Service]
WatchdogSec=30
ExecStartPost=/bin/bash -c 'sleep 2 && curl -sf http://127.0.0.1:8080/health || exit 1'
```

### 负载均衡器健康检查

如果在 Nginx/HAProxy 后面：

```nginx title="nginx.conf 示例"
upstream clawsentry {
    server 127.0.0.1:8080;
}

server {
    location /health {
        proxy_pass http://clawsentry;
    }

    location / {
        proxy_pass http://clawsentry;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # SSE 支持
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
    }
}
```

!!! warning "SSE 代理注意事项"
    反向代理 SSE 连接时，必须禁用缓冲（`proxy_buffering off`）并使用 HTTP/1.1。否则 SSE 事件会被缓冲，导致客户端无法实时接收。

---

## IP 白名单

如果使用 OpenClaw Webhook 接收方式，可以配置 IP 白名单限制来源：

```bash
# 只允许本地和内网地址
AHP_WEBHOOK_IP_WHITELIST=127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
```

支持单个 IP 和 CIDR 网段表示法。

---

## 速率限制

Gateway 内置速率限制，防止过载：

```bash
# 每分钟最大请求数（默认 300）
AHP_RATE_LIMIT_PER_MINUTE=300
```

超过限制时，API 返回 `RATE_LIMITED` 错误码，RPC 响应包含 `retry_after_ms` 字段。

---

## Docker 部署

!!! note "参考配置"
    ClawSentry 尚未提供官方 Docker 镜像，以下为参考 Dockerfile。

```dockerfile title="Dockerfile"
FROM python:3.12-slim

# 安装 ClawSentry
RUN pip install --no-cache-dir "clawsentry[llm]"

# 创建非 root 用户
RUN useradd --system --no-create-home clawsentry
USER clawsentry

# 数据目录
RUN mkdir -p /var/lib/clawsentry
VOLUME /var/lib/clawsentry

# 暴露端口
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -sf http://127.0.0.1:8080/health || exit 1

# 启动 Gateway
ENTRYPOINT ["clawsentry", "gateway"]
```

```bash title="docker-compose.yml"
services:
  clawsentry:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - clawsentry-data:/var/lib/clawsentry
    environment:
      CS_AUTH_TOKEN: ${CS_AUTH_TOKEN}
      CS_TRAJECTORY_DB_PATH: /var/lib/clawsentry/trajectory.db
      CS_HTTP_HOST: 0.0.0.0
      # 如果需要 LLM 分析
      # CS_LLM_PROVIDER: openai
      # OPENAI_API_KEY: ${OPENAI_API_KEY}
    restart: unless-stopped

volumes:
  clawsentry-data:
```

---

## 安全清单

部署到生产环境前，请逐项确认以下检查项：

### 认证与授权

- [x] `CS_AUTH_TOKEN` 已设置为强随机令牌（>= 32 字节）
- [x] 不使用默认或示例令牌
- [x] 令牌不出现在代码仓库或日志中

### 传输安全

- [x] 启用 SSL/TLS（`AHP_SSL_CERTFILE` + `AHP_SSL_KEYFILE`）
- [x] SSL 私钥文件权限为 600
- [x] UDS 路径在受限目录下，权限为 600

### 网络

- [x] Gateway 不直接暴露在公网（通过反向代理或 VPN）
- [x] 如果使用 Webhook，配置了 IP 白名单
- [x] 速率限制已配置

### 数据

- [x] `CS_TRAJECTORY_DB_PATH` 指向持久化存储
- [x] 数据库文件有定期备份
- [x] 数据目录权限仅限运行用户

### 运行时

- [x] 以非 root 用户运行（systemd `User=clawsentry`）
- [x] systemd 安全加固选项已启用（`NoNewPrivileges`, `ProtectSystem`）
- [x] 日志输出到文件或 journald，有轮转策略
- [x] 健康检查已配置

### LLM 安全

- [x] LLM API Key 通过环境变量注入，不硬编码
- [x] LLM 请求超时已配置（默认 3 秒）
- [x] L3 Agent 的 ReadOnlyToolkit 确保只读访问

### 监控

- [x] 健康检查端点 `/health` 已加入监控系统
- [x] SSE 事件流可观测（通过仪表板或 `clawsentry watch`）
- [x] 告警通知渠道已配置
