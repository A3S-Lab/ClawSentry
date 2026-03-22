# ClawSentry — AHP 安全监督网关

> **Python 3.11+** | **775 tests** | 协议版本 `ahp.1.0`

**ClawSentry** 是 AHP（Agent Harness Protocol）的 Python 参考实现，面向多 Agent 框架的统一安全监督网关。它以 Sidecar 形式部署，将来自不同运行时（a3s-code、OpenClaw 等）的事件归一化为统一协议，经过三层递进式风险评估后产生实时决策（放行 / 拦截 / 修改 / 延迟），并保留完整的审计轨迹。

**核心目标**：消除跨框架的策略重复实现与可观测性碎片化，用"协议优先、决策集中"的方式统一 Agent 安全监管。

---

## 目录

- [三层决策模型](#三层决策模型)
- [架构概览](#架构概览)
- [快速开始](#快速开始)
- [CLI 命令](#cli-命令)
- [API 端点](#api-端点)
- [Web 安全仪表板](#web-安全仪表板)
- [项目结构](#项目结构)
- [配置参数](#配置参数)
- [运行测试](#运行测试)
- [设计文档索引](#设计文档索引)

---

## 三层决策模型

本框架采用**分层递进**的评估架构，每层有明确的延迟预算和职责边界：

```
                    事件流量 100%
                        │
                 ┌──────▼──────┐
                 │  L1 规则引擎  │  ← 确定性规则，< 1ms
                 └──────┬──────┘
                        │
            ┌───────────┼───────────┐
            ▼           ▼           ▼
     LOW (allow)   MEDIUM (?)   CRITICAL (block)
      ~60%流量      ~30%流量      ~10%流量
         │              │           │
         │       ┌──────▼──────┐   │
         │       │  L2 语义引擎  │   │  ← 可插拔 LLM，< 3s
         │       └──────┬──────┘   │
         │              │          │
         │       ┌──────▼──────┐   │
         │       │  L3 审查Agent │   │  ← 多轮工具调用，< 30s
         │       └──────┬──────┘   │
         │              │          │
         ▼              ▼          ▼
       allow      allow/block    block
```

| 层级 | 实现 | 延迟 | 依赖 | 激活方式 |
|------|------|------|------|---------|
| **L1** 规则引擎 | D1-D5 五维评分 + 短路规则 | < 1ms | 无 | 默认启用 |
| **L2** 语义分析 | RuleBased / LLM / Composite | < 3s | Anthropic/OpenAI API (可选) | `CS_LLM_PROVIDER` 环境变量 |
| **L3** 审查 Agent | AgentAnalyzer + ReadOnlyToolkit + SkillRegistry | < 30s | LLM API | `CS_L3_ENABLED=true` |

### D1-D5 五维风险评估

| 维度 | 评估对象 | 分值 |
|------|---------|------|
| **D1** 工具类型 | 工具本身的风险等级 (bash=3, read_file=0) | 0-3 |
| **D2** 目标路径 | 操作涉及的文件/路径 (/etc/passwd=3, /tmp=0) | 0-3 |
| **D3** 命令模式 | bash/exec 命令内容 (rm -rf=3, ls=0) | 0-3 |
| **D4** 会话累积 | 该会话已发生的高危事件数 | 0-2 |
| **D5** 信任等级 | Agent 的权限层级 | 0-2 |

**短路规则**：D1=3 且 D2>=2 → CRITICAL | D3=3 → CRITICAL | D1=D2=D3=0 → LOW

---

## 架构概览

```
 ┌──────────────────────────────────────────────────────────────────┐
 │              Framework Runtime Layer                              │
 │  ┌──────────────────┐          ┌─────────────────────────┐      │
 │  │ a3s-code (Rust)   │          │  OpenClaw (TypeScript)   │      │
 │  │   stdio Hook      │          │  WS exec.approval        │      │
 │  └────────┬─────────┘          └──────────┬──────────────┘      │
 └───────────┼───────────────────────────────┼─────────────────────┘
             │                               │
 ┌───────────▼───────────────────────────────▼─────────────────────┐
 │                    Adapter Layer                                  │
 │  ┌──────────────────┐     ┌──────────────────────────────┐      │
 │  │  A3SCodeAdapter   │     │  OpenClawAdapter + WS Client │      │
 │  │  + Harness 桥接   │     │  + Webhook Receiver          │      │
 │  └────────┬─────────┘     └──────────┬───────────────────┘      │
 └───────────┼──────────────────────────┼──────────────────────────┘
             │   UDS / HTTP (JSON-RPC)  │
 ┌───────────▼──────────────────────────▼──────────────────────────┐
 │              ClawSentry — AHP Supervision Gateway                 │
 │                                                                   │
 │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐   │
 │  │ L1 Rules │→│ L2 LLM   │→│ L3 Agent │→│ Decision Router │   │
 │  │ D1-D5    │  │ Semantic │  │ Toolkit  │  │ allow/block/   │   │
 │  │ <1ms     │  │ <3s      │  │ <30s     │  │ modify/defer   │   │
 │  └──────────┘  └──────────┘  └──────────┘  └───────┬────────┘   │
 │                                                      │            │
 │  ┌─────────────────┐  ┌────────────────┐  ┌─────────▼────────┐  │
 │  │ SessionRegistry  │  │  AlertRegistry │  │ TrajectoryStore  │  │
 │  │ 会话风险跟踪     │  │  告警管理      │  │ SQLite 审计轨迹  │  │
 │  └─────────────────┘  └────────────────┘  └──────────────────┘  │
 │                                                                   │
 │  ┌─────────────────┐  ┌────────────────┐  ┌──────────────────┐  │
 │  │ EventBus + SSE  │  │ Idempotency    │  │ Web Dashboard    │  │
 │  │ 实时事件推送     │  │ Cache (去重)   │  │ React SPA at /ui │  │
 │  └─────────────────┘  └────────────────┘  └──────────────────┘  │
 └──────────────────────────────────────────────────────────────────┘
```

**设计原则**：

| 原则 | 说明 |
|------|------|
| 协议优先 | 先解决跨框架互操作，再叠加策略 |
| 决策集中 | 所有最终决策由 Gateway 产生，Adapter 不做决策 |
| 双通道处理 | pre-action 同步拦截，post-action 异步审计 |
| 仅升级不降级 | L2/L3 只能把风险往上调，确保安全下限 |
| fail-closed | 高危操作在 Gateway 不可达时默认拦截 |

---

## 快速开始

### 安装

```bash
# 基础安装
pip install clawsentry

# 含 OpenClaw WS 集成
pip install "clawsentry[enforcement]"

# 含 LLM 语义分析
pip install "clawsentry[llm]"

# 全量安装（含开发依赖）
pip install "clawsentry[all]"

# 开发模式（从源码）
git clone <repo-url> && cd ClawSentry
pip install -e ".[dev]"
```

### OpenClaw 用户（推荐流程）

```bash
# 1. 一键初始化（自动探测 ~/.openclaw/openclaw.json 提取 token/端口）
clawsentry init openclaw --auto-detect

# 2. 自动配置 OpenClaw（设置 tools.exec.host + exec-approvals）
clawsentry init openclaw --setup

# 3. 启动 Gateway（自动检测 OpenClaw 配置，按需启动 WS/Webhook）
clawsentry gateway

# 4. 实时监控（另一终端）
clawsentry watch

# 5. Web 仪表板
# 浏览器打开 http://127.0.0.1:8080/ui
```

### a3s-code 用户

```bash
# 1. 初始化配置
clawsentry init a3s-code

# 2. 启动 Gateway
clawsentry gateway

# 3. 在 a3s-code 中配置 AHP transport
#    opts.ahp_transport = StdioTransport(program="clawsentry-harness")

# 4. 实时监控
clawsentry watch
```

### 直接调用 Gateway (JSON-RPC)

```bash
# 通过 HTTP 发送决策请求
curl -X POST http://127.0.0.1:8080/ahp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-token>" \
  -d '{
    "jsonrpc": "2.0",
    "method": "ahp/sync_decision",
    "id": "req-001",
    "params": {
      "rpc_version": "sync_decision.1.0",
      "request_id": "req-001",
      "deadline_ms": 100,
      "decision_tier": "L1",
      "event": {
        "schema_version": "ahp.1.0",
        "event_id": "evt-001",
        "trace_id": "trace-001",
        "event_type": "pre_action",
        "session_id": "sess-abc",
        "agent_id": "agent-001",
        "source_framework": "a3s-code",
        "occurred_at": "2025-01-01T00:00:00Z",
        "payload": {"tool": "bash", "command": "ls"},
        "event_subtype": "tool:execute"
      }
    }
  }'
```

---

## CLI 命令

统一入口 `clawsentry`，行为由配置自动决定：

| 命令 | 说明 |
|------|------|
| `clawsentry gateway` | 启动 Gateway（自动检测 OpenClaw 配置，按需启动 WS/Webhook） |
| `clawsentry watch` | 连接 SSE 实时展示决策（`--filter`/`--json`/`--no-color`/`--interactive`） |
| `clawsentry init <framework>` | 一键初始化配置（`openclaw`/`a3s-code`） |
| `clawsentry init openclaw --auto-detect` | 自动探测 `~/.openclaw/openclaw.json` 提取 token/端口 |
| `clawsentry init openclaw --setup` | 自动配置 OpenClaw（`tools.exec.host` + `exec-approvals`） |
| `clawsentry harness` | a3s-code stdio 桥接子进程 |

**环境变量自动加载**：Gateway 启动时自动读取 `.env.clawsentry` 文件（不覆盖已有环境变量）。

---

## API 端点

所有端点需 `Authorization: Bearer <token>` 认证（`/health` 和 `/ui` 除外）。SSE 端点支持 `?token=xxx` query param 认证（`EventSource` 不支持自定义 header）。

### 决策

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/ahp` | JSON-RPC 同步决策（ahp/sync_decision） |
| POST | `/ahp/resolve` | DEFER 决策代理（allow-once/deny），503 当无 OpenClaw |

### 报表 & 监控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（无需认证，K8s probe 兼容） |
| GET | `/report/summary` | 跨框架聚合统计（支持 `window_seconds` 参数） |
| GET | `/report/sessions` | 活跃会话列表 + 风险排序 |
| GET | `/report/session/{id}` | 会话轨迹回放 |
| GET | `/report/session/{id}/risk` | 会话风险详情 + D1-D5 时间线 |
| GET | `/report/stream` | SSE 实时事件推送（decision/session_start/session_risk_change/alert） |
| GET | `/report/alerts` | 告警列表（过滤: severity/acknowledged/window_seconds） |
| POST | `/report/alerts/{id}/acknowledge` | 确认告警 |

### Web 界面

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ui` | Web 安全仪表板 SPA（无需认证） |

---

## Web 安全仪表板

Gateway 内置 React SPA 安全仪表板，通过 `/ui` 路径访问。暗色 SOC 主题，实时 SSE 数据推送。

| 页面 | 功能 |
|------|------|
| **Dashboard** | 实时决策 feed + 4 指标卡 + 风险分布图 + 决策来源图 |
| **Sessions** | 活跃会话列表 + D1-D5 雷达图 + 风险曲线 + 决策时间线 |
| **Alerts** | 告警表格 + severity/acknowledged 过滤 + 确认按钮 + SSE 自动推送 |
| **DEFER Panel** | 待决策列表 + 倒计时器 + Allow/Deny 按钮 + 503 降级提示 |

技术栈：React 18 + TypeScript + Vite + recharts + lucide-react

---

## 项目结构

```
src/clawsentry/
├── gateway/                           # 核心监督引擎
│   ├── models.py                      # 统一数据模型 (CanonicalEvent / Decision / RiskSnapshot)
│   ├── server.py                      # FastAPI HTTP + UDS 双传输 + Auth + SSE + 静态文件
│   ├── stack.py                       # 一键启动 Gateway + OpenClaw 运行时 + DEFER resolve
│   ├── policy_engine.py               # L1 规则 + L2 Analyzer 集成
│   ├── risk_snapshot.py               # D1-D5 五维风险评估
│   ├── semantic_analyzer.py           # L2 可插拔语义分析 (Protocol + 3 种实现)
│   ├── llm_provider.py                # LLM Provider 基类 (Anthropic/OpenAI)
│   ├── llm_factory.py                 # 环境变量驱动 analyzer 构建
│   ├── agent_analyzer.py              # L3 审查 Agent (MVP 单轮 + 标准多轮)
│   ├── review_toolkit.py              # L3 ReadOnlyToolkit (5 个只读工具)
│   ├── review_skills.py               # L3 SkillRegistry (YAML 加载/选择)
│   ├── l3_trigger.py                  # L3 触发策略 (4 类触发条件)
│   ├── idempotency.py                 # 请求幂等性缓存
│   └── skills/                        # 6 个内置审查领域 skill (YAML)
├── adapters/                          # 框架适配器
│   ├── a3s_adapter.py                 # a3s-code Hook → CanonicalEvent 归一化
│   ├── a3s_gateway_harness.py         # a3s-code stdio 桥接 (JSON-RPC 2.0)
│   ├── openclaw_adapter.py            # OpenClaw 主适配器 (含审批状态机)
│   ├── openclaw_normalizer.py         # OpenClaw 事件归一化
│   ├── openclaw_ws_client.py          # OpenClaw WS 客户端 (事件监听 + resolve)
│   ├── openclaw_webhook_receiver.py   # OpenClaw Webhook 安全接收器
│   ├── openclaw_gateway_client.py     # OpenClaw → Gateway RPC 客户端
│   ├── openclaw_approval.py           # 审批生命周期状态机
│   ├── openclaw_bootstrap.py          # OpenClaw 统一配置工厂
│   └── webhook_security.py            # Token + HMAC 校验
├── cli/                               # 统一 CLI
│   ├── main.py                        # clawsentry 入口 (init/gateway/watch/harness)
│   ├── init_command.py                # init 命令 + --setup + --auto-detect
│   ├── watch_command.py               # watch SSE 实时终端 + --interactive DEFER
│   ├── dotenv_loader.py               # .env.clawsentry 自动加载
│   └── initializers/                  # 框架初始化器 (openclaw/a3s_code)
├── ui/                                # Web 安全仪表板 (React SPA)
│   ├── src/                           # TypeScript 源码
│   │   ├── api/                       # API client + SSE + types
│   │   ├── hooks/                     # useAuth
│   │   ├── components/                # Layout, StatusBar, badges, etc.
│   │   └── pages/                     # Dashboard, Sessions, Alerts, DeferPanel
│   └── dist/                          # 预构建产物 (随 pip 包分发)
└── tests/                             # 测试套件 (775 tests)
```

---

## 配置参数

### 核心环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CS_AUTH_TOKEN` | (禁用) | HTTP 端点 Bearer token（建议 >= 32 字符） |
| `CS_HTTP_HOST` | `127.0.0.1` | HTTP 绑定地址 |
| `CS_HTTP_PORT` | `8080` | HTTP 端口 |
| `CS_UDS_PATH` | `/tmp/clawsentry.sock` | UDS 监听地址 |
| `CS_TRAJECTORY_DB_PATH` | `/tmp/clawsentry-trajectory.db` | SQLite 轨迹文件 |

### LLM 配置

| 变量 | 说明 |
|------|------|
| `CS_LLM_PROVIDER` | LLM 提供商 (`anthropic` / `openai`) |
| `CS_LLM_BASE_URL` | 自定义 API 端点 |
| `CS_LLM_MODEL` | 模型名称 |
| `CS_L3_ENABLED` | 启用 L3 审查 Agent (`true`/`false`) |

### OpenClaw 配置

| 变量 | 说明 |
|------|------|
| `OPENCLAW_WS_URL` | OpenClaw Gateway WS 地址 |
| `OPENCLAW_OPERATOR_TOKEN` | 操作员令牌 |
| `OPENCLAW_ENFORCEMENT_ENABLED` | 启用执法模式 (`true`/`false`) |
| `OPENCLAW_WEBHOOK_TOKEN` | Webhook 认证 token |
| `OPENCLAW_WEBHOOK_SECRET` | Webhook HMAC 签名密钥 |

### 会话强制策略

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AHP_SESSION_ENFORCEMENT_ENABLED` | `false` | 启用会话级累积高危强制策略 |
| `AHP_SESSION_ENFORCEMENT_THRESHOLD` | `3` | 触发强制的高危事件累积阈值 |
| `AHP_SESSION_ENFORCEMENT_ACTION` | `defer` | 触发后的动作 (`defer`/`block`/`l3_require`) |
| `AHP_SESSION_ENFORCEMENT_COOLDOWN_SECONDS` | `600` | 强制状态冷却时间（秒） |

### 安全加固

| 变量 | 说明 |
|------|------|
| `CS_RATE_LIMIT_PER_MINUTE` | 速率限制（默认 300/分钟） |
| `AHP_SSL_CERTFILE` | SSL 证书路径（启用 HTTPS） |
| `AHP_SSL_KEYFILE` | SSL 私钥路径 |
| `AHP_WEBHOOK_IP_WHITELIST` | Webhook 来源 IP 白名单（逗号分隔） |
| `AHP_WEBHOOK_TOKEN_TTL_SECONDS` | Webhook Token 有效期（秒） |
| `AHP_SKILLS_DIR` | L3 自定义 Skills 目录路径 |

---

## 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行全部测试
python -m pytest src/clawsentry/tests/ -v --tb=short
# 预期：775 passed

# 按模块运行
python -m pytest src/clawsentry/tests/test_risk_and_policy.py -v    # L1 风险评估
python -m pytest src/clawsentry/tests/test_semantic_analyzer.py -v  # L2 语义分析
python -m pytest src/clawsentry/tests/test_agent_analyzer.py -v     # L3 审查 Agent
python -m pytest src/clawsentry/tests/test_gateway.py -v            # Gateway 协议
python -m pytest src/clawsentry/tests/test_openclaw_adapter.py -v   # OpenClaw 适配器
python -m pytest src/clawsentry/tests/test_ws_gateway_integration.py -v  # WS 全链路集成
python -m pytest src/clawsentry/tests/test_a3s_e2e_integration.py -v     # a3s-code E2E
python -m pytest src/clawsentry/tests/test_http_auth.py -v          # HTTP 认证
python -m pytest src/clawsentry/tests/test_resolve_endpoint.py -v   # DEFER resolve
python -m pytest src/clawsentry/tests/test_ui_static.py -v          # Web UI 静态文件
python -m pytest src/clawsentry/tests/test_cli_init.py -v           # CLI init
python -m pytest src/clawsentry/tests/test_watch_command.py -v      # watch 命令
```

---

## 设计文档索引

详细设计文档位于 `docs/designs/ClawSentry/`:

| 文档 | 内容 | 状态 |
|------|------|------|
| `01-scope-and-architecture.md` | 整体范围、架构层次、部署模型 | FROZEN |
| `02-unified-ahp-contract.md` | Canonical Event / Decision 统一合约 | FROZEN |
| `03-openclaw-adapter-design.md` | OpenClaw 适配器设计 | FROZEN |
| `04-policy-decision-and-fallback.md` | 决策模型、风险评分、超时/重试/降级 | FROZEN |
| `05-trajectory-observability-audit.md` | 审计轨迹与合规报告 | FROZEN |
| `06-rollout-validation-and-risks.md` | 分阶段上线风险与验证检查点 | FROZEN |
| `07-openclaw-field-level-mapping.md` | OpenClaw 字段级映射 | FROZEN |
| `08-openclaw-webhook-security-hardening.md` | Webhook 安全补强方案 | FROZEN |
| `09-l2-pluggable-semantic-analysis.md` | L2 可插拔语义分析架构 | FROZEN |
| `10-http-endpoint-auth.md` | HTTP Bearer Token 认证 | FROZEN |
| `11-long-term-evolution-vision.md` | 长期演进路线图 (Phase 5+) | ACTIVE |
