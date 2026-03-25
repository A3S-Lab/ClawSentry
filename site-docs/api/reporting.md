---
title: 报表与监控
description: ClawSentry 报表、会话管理、告警和 SSE 实时推送端点的完整参考
---

# 报表与监控端点

ClawSentry Gateway 提供一整套 HTTP API 用于健康检查、聚合统计、会话追踪、告警管理和实时事件流推送。所有 `/report/*` 端点均需 Bearer Token 认证（除非 `CS_AUTH_TOKEN` 为空）。

!!! abstract "本页快速导航"
    [GET /health](#get-health) · [GET /report/summary](#get-report-summary) · [GET /report/sessions](#get-report-sessions) · [GET /report/session/{id}](#get-report-session) · [GET /report/stream (SSE)](#get-report-stream) · [GET /report/alerts](#get-report-alerts) · [POST /report/alerts/{id}/ack](#post-report-alerts-acknowledge)

---

## GET /health — 健康检查 {#get-health}

返回 Gateway 的运行状态。此端点**不需要认证**。

### 响应

```json
{
  "status": "healthy",
  "uptime_seconds": 3600.5,
  "cache_size": 12,
  "trajectory_count": 4523,
  "trajectory_backend": "sqlite",
  "policy_engine": "L1+L2",
  "rpc_version": "sync_decision.1.0",
  "auth_enabled": true
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 运行状态，始终为 `"healthy"` |
| `uptime_seconds` | float | 进程运行时间（秒） |
| `cache_size` | int | 幂等性缓存当前条目数 |
| `trajectory_count` | int | 轨迹数据库总记录数 |
| `trajectory_backend` | string | 持久化后端类型 |
| `policy_engine` | string | 当前启用的决策层 |
| `rpc_version` | string | 支持的 RPC 协议版本 |
| `auth_enabled` | bool | HTTP 认证是否启用 |

### curl 示例

```bash
curl http://127.0.0.1:8080/health
```

---

## GET /report/summary — 聚合统计 {#get-report-summary}

跨框架聚合统计，涵盖事件分布、决策分布、风险趋势等。

### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `window_seconds` | int | `null`（全部） | 时间窗口限制（1 ~ 604800 秒） |

### 响应

```json
{
  "total_records": 1250,
  "by_source_framework": {
    "a3s-code": 800,
    "openclaw": 450
  },
  "by_event_type": {
    "pre_action": 900,
    "post_action": 300,
    "session": 50
  },
  "by_decision": {
    "allow": 1000,
    "block": 150,
    "defer": 80,
    "modify": 20
  },
  "by_risk_level": {
    "low": 800,
    "medium": 300,
    "high": 120,
    "critical": 30
  },
  "by_actual_tier": {
    "L1": 1200,
    "L2": 50
  },
  "by_caller_adapter": {
    "a3s-adapter.v1": 800,
    "openclaw-adapter.v1": 450
  },
  "invalid_event": {
    "count_1m": 0,
    "count_5m": 2,
    "count_15m": 5,
    "rate_5m": 0.004,
    "rate_15m": 0.002,
    "alerts": []
  },
  "high_risk_trend": {
    "windows": {
      "5m": {"count": 3, "total": 50, "ratio": 0.06},
      "15m": {"count": 8, "total": 150, "ratio": 0.053},
      "60m": {"count": 20, "total": 500, "ratio": 0.04}
    },
    "direction_5m": "up",
    "series_5m": [
      {
        "bucket_start": "2026-03-23T09:00:00+00:00",
        "bucket_end": "2026-03-23T09:05:00+00:00",
        "total_count": 40,
        "high_or_critical_count": 2,
        "ratio": 0.05
      }
    ]
  },
  "generated_at": "2026-03-23T10:30:00+00:00",
  "window_seconds": null
}
```

**关键指标说明：**

- `invalid_event` —— 无效事件计数与速率，超过阈值时触发告警
    - `count_1m > 20` → `critical` 告警
    - `rate_5m > 1%` → `critical` 告警
    - `rate_15m 在 0.1%-1%` → `warning` 告警
- `high_risk_trend` —— 高风险事件趋势
    - `direction_5m`: `up`（上升）/ `down`（下降）/ `flat`（持平）
    - `series_5m`: 最近 12 个 5 分钟桶的时序数据

### curl 示例

```bash
# 全量统计
curl -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  http://127.0.0.1:8080/report/summary

# 最近 1 小时
curl -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  "http://127.0.0.1:8080/report/summary?window_seconds=3600"
```

---

## GET /report/sessions — 活跃会话列表 {#get-report-sessions}

返回当前内存中的活跃会话列表，支持按风险等级排序和过滤。

### 查询参数

| 参数 | 类型 | 默认值 | 可选值 | 说明 |
|------|------|--------|--------|------|
| `status` | string | `active` | `active`, `all` | 会话状态过滤 |
| `sort` | string | `risk_level` | `risk_level`, `last_event` | 排序方式 |
| `limit` | int | `50` | 1-200 | 返回条目数量上限 |
| `min_risk` | string | `null` | `low`, `medium`, `high`, `critical` | 最低风险等级过滤 |
| `window_seconds` | int | `null` | 1-604800 | 时间窗口（按最后活动时间） |

### 响应

```json
{
  "sessions": [
    {
      "session_id": "session-001",
      "agent_id": "agent-001",
      "source_framework": "a3s-code",
      "caller_adapter": "a3s-adapter.v1",
      "current_risk_level": "high",
      "cumulative_score": 5,
      "event_count": 25,
      "high_risk_event_count": 3,
      "decision_distribution": {
        "allow": 20,
        "block": 3,
        "defer": 2
      },
      "first_event_at": "2026-03-23T10:00:00+00:00",
      "last_event_at": "2026-03-23T10:30:00+00:00",
      "d4_accumulation": 4
    }
  ],
  "total_active": 15,
  "generated_at": "2026-03-23T10:31:00+00:00",
  "window_seconds": null
}
```

### curl 示例

```bash
# 按风险排序，前 10 个会话
curl -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  "http://127.0.0.1:8080/report/sessions?sort=risk_level&limit=10"

# 仅高风险会话
curl -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  "http://127.0.0.1:8080/report/sessions?min_risk=high"
```

---

## GET /report/session/{id} — 会话轨迹回放 {#get-report-session}

返回指定会话的完整事件与决策轨迹（从 SQLite 轨迹数据库查询）。

### 路径参数

| 参数 | 说明 |
|------|------|
| `id` | 会话 ID |

### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | `100` | 最大返回记录数（1-1000） |
| `window_seconds` | int | `null` | 时间窗口限制 |

### 响应

```json
{
  "session_id": "session-001",
  "record_count": 3,
  "records": [
    {
      "event": {
        "event_id": "evt-001",
        "event_type": "pre_action",
        "tool_name": "bash",
        "session_id": "session-001",
        "source_framework": "a3s-code",
        "occurred_at": "2026-03-23T10:00:00+00:00",
        "payload": {"command": "ls -la"}
      },
      "decision": {
        "decision": "allow",
        "reason": "Low risk operation",
        "risk_level": "low",
        "policy_id": "L1-default-allow"
      },
      "risk_snapshot": {
        "risk_level": "low",
        "composite_score": 1,
        "dimensions": {"d1": 1, "d2": 0, "d3": 0, "d4": 0, "d5": 0},
        "classified_by": "L1"
      },
      "meta": {
        "request_id": "a3s-evt-001-...",
        "actual_tier": "L1",
        "deadline_ms": 100,
        "caller_adapter": "a3s-adapter.v1"
      },
      "recorded_at": "2026-03-23T10:00:00.001+00:00",
      "recorded_at_ts": 1774530000.001,
      "l3_trace": null
    }
  ],
  "generated_at": "2026-03-23T10:31:00+00:00",
  "window_seconds": null
}
```

### curl 示例

```bash
curl -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  "http://127.0.0.1:8080/report/session/session-001?limit=50"
```

---

## GET /report/session/{id}/risk — 会话风险详情 {#get-report-session-risk}

返回指定会话的实时风险状态，包括 D1-D5 维度得分、风险时间线和使用的工具列表。

### 路径参数

| 参数 | 说明 |
|------|------|
| `id` | 会话 ID |

### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | `100` | 时间线最大条目数（1-1000） |
| `window_seconds` | int | `null` | 时间窗口限制 |

### 响应

```json
{
  "session_id": "session-001",
  "current_risk_level": "high",
  "cumulative_score": 5,
  "dimensions_latest": {
    "d1": 3,
    "d2": 2,
    "d3": 1,
    "d4": 1,
    "d5": 0
  },
  "risk_timeline": [
    {
      "event_id": "evt-001",
      "occurred_at": "2026-03-23T10:00:00+00:00",
      "risk_level": "low",
      "composite_score": 1,
      "tool_name": "bash",
      "decision": "allow"
    },
    {
      "event_id": "evt-002",
      "occurred_at": "2026-03-23T10:05:00+00:00",
      "risk_level": "high",
      "composite_score": 5,
      "tool_name": "bash",
      "decision": "block"
    }
  ],
  "risk_hints_seen": ["destructive_pattern", "shell_execution"],
  "tools_used": ["bash", "file_editor"],
  "actual_tier_distribution": {
    "L1": 23,
    "L2": 2
  },
  "generated_at": "2026-03-23T10:31:00+00:00",
  "window_seconds": null
}
```

**字段说明：**

| 字段 | 说明 |
|------|------|
| `dimensions_latest` | 该会话最新一次评估的 D1-D5 维度得分 |
| `risk_timeline` | 风险变化时间线（按事件发生时间排序） |
| `risk_hints_seen` | 该会话曾触发的所有风险提示集合 |
| `tools_used` | 该会话使用过的工具集合 |
| `actual_tier_distribution` | 各决策层级的使用次数分布 |

### curl 示例

```bash
curl -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  "http://127.0.0.1:8080/report/session/session-001/risk"
```

---

## GET /report/session/{id}/enforcement — 会话强制策略状态 {#get-report-session-enforcement}

查询指定会话的强制执行策略状态（A-7 会话级强制策略）。

### 响应 — 正常状态

```json
{
  "session_id": "session-001",
  "state": "normal",
  "action": null,
  "triggered_at": null,
  "last_high_risk_at": null,
  "high_risk_count": null
}
```

### 响应 — 强制状态

```json
{
  "session_id": "session-001",
  "state": "enforced",
  "action": "defer",
  "triggered_at": 1774530000.0,
  "last_high_risk_at": 1774530300.0,
  "high_risk_count": 5
}
```

| 字段 | 说明 |
|------|------|
| `state` | `normal`（正常）或 `enforced`（强制中） |
| `action` | 强制执行的动作：`defer`、`block` 或 `l3_require` |
| `triggered_at` | 强制策略触发时间（monotonic 时间戳） |
| `last_high_risk_at` | 最后一次高风险事件时间 |
| `high_risk_count` | 高风险事件累计数量 |

### curl 示例

```bash
curl -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  http://127.0.0.1:8080/report/session/session-001/enforcement
```

---

## POST /report/session/{id}/enforcement — 手动释放强制策略 {#post-report-session-enforcement}

手动释放指定会话的强制执行策略，无需等待 cooldown 自然过期。

### 请求

```json
{
  "action": "release"
}
```

!!! warning "`action` 必须为 `\"release\"`"
    当前仅支持 `release` 操作。其他值返回 400 错误。

### 成功响应

```json
{
  "session_id": "session-001",
  "released": true
}
```

如果会话未处于强制状态：

```json
{
  "session_id": "session-001",
  "released": false
}
```

释放后，Gateway 会通过 SSE 广播 `session_enforcement_change` 事件（`state: "released"`）。

### curl 示例

```bash
curl -X POST http://127.0.0.1:8080/report/session/session-001/enforcement \
  -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "release"}'
```

---

## GET /report/stream — SSE 实时事件流 {#get-report-stream}

Server-Sent Events (SSE) 端点，提供实时的决策、告警和会话变更推送。

### 认证

支持两种认证方式：

1. **Header**: `Authorization: Bearer <token>`
2. **Query Param**: `?token=<token>`

!!! info "为什么支持 Query Param 认证"
    浏览器的 `EventSource` API 不支持自定义 HTTP 头，因此提供 query param 方式作为替代。

### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_id` | string | `null` | 仅推送指定会话的事件 |
| `min_risk` | string | `null` | 最低风险等级过滤（`low`/`medium`/`high`/`critical`） |
| `types` | string | 全部 | 逗号分隔的事件类型 |

**`types` 可选值：**

`decision`, `session_start`, `session_risk_change`, `alert`, `session_enforcement_change`

### SSE 协议格式

```
: connected

event: decision
data: {"session_id":"session-001","event_id":"evt-001","risk_level":"high","decision":"block","tool_name":"bash","actual_tier":"L1","timestamp":"2026-03-23T10:30:00+00:00","reason":"D1: destructive tool","command":"rm -rf /data","approval_id":null,"expires_at":null}

event: session_start
data: {"session_id":"session-002","agent_id":"agent-002","source_framework":"openclaw","timestamp":"2026-03-23T10:31:00+00:00"}

event: session_risk_change
data: {"session_id":"session-001","previous_risk":"medium","current_risk":"high","trigger_event":"evt-002","timestamp":"2026-03-23T10:32:00+00:00"}

event: alert
data: {"alert_id":"alert-abc123","severity":"high","metric":"session_risk_escalation","session_id":"session-001","current_risk":"high","message":"Session risk escalated to HIGH: 3 high-risk event(s) detected","timestamp":"2026-03-23T10:32:00+00:00"}

event: session_enforcement_change
data: {"session_id":"session-001","state":"enforced","action":"defer","high_risk_count":3,"timestamp":"2026-03-23T10:32:00+00:00"}

: keepalive
```

**协议细节：**

- `: connected` —— 连接确认注释（立即刷新 HTTP 头）
- `: keepalive` —— 15 秒无事件时发送心跳
- 每个 SSE 订阅者有独立队列（最大 500 条），队满时丢弃最旧事件
- 最大并发订阅者数：100

### 各事件类型的 data 字段

#### decision

| 字段 | 说明 |
|------|------|
| `session_id` | 会话 ID |
| `event_id` | 事件 ID |
| `risk_level` | 风险等级 |
| `decision` | 判决（allow/block/defer/modify） |
| `tool_name` | 工具名称 |
| `actual_tier` | 实际决策层 |
| `timestamp` | 事件时间戳 |
| `reason` | 决策原因 |
| `command` | 执行的命令 |
| `approval_id` | 审批 ID（DEFER 时有值） |
| `expires_at` | 审批超时时间（epoch 毫秒） |

#### alert

| 字段 | 说明 |
|------|------|
| `alert_id` | 告警 ID |
| `severity` | 严重程度（high/critical） |
| `metric` | 告警指标名 |
| `session_id` | 关联会话 |
| `current_risk` | 当前风险等级 |
| `message` | 告警消息 |
| `timestamp` | 触发时间 |

### curl / JavaScript 示例

```bash
# curl（流式输出）
curl -N -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  "http://127.0.0.1:8080/report/stream?types=decision,alert"

# 仅高风险事件
curl -N -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  "http://127.0.0.1:8080/report/stream?min_risk=high"
```

```javascript
// 浏览器 EventSource（使用 query param 认证）
const es = new EventSource(
  "http://127.0.0.1:8080/report/stream?token=my-secret-token&types=decision,alert"
);

es.addEventListener("decision", (e) => {
  const data = JSON.parse(e.data);
  console.log(`[${data.decision}] ${data.command} — ${data.reason}`);
});

es.addEventListener("alert", (e) => {
  const data = JSON.parse(e.data);
  console.warn(`ALERT: ${data.message}`);
});
```

---

## GET /report/alerts — 告警列表 {#get-report-alerts}

返回告警列表，支持按严重程度、确认状态和时间窗口过滤。

### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `severity` | string | `null` | 过滤严重程度：`low`/`medium`/`high`/`critical` |
| `acknowledged` | string | `null` | 过滤确认状态：`true`/`false` |
| `window_seconds` | int | `null` | 时间窗口限制 |
| `limit` | int | `100` | 返回条目数量上限（1-1000） |

### 响应

```json
{
  "alerts": [
    {
      "alert_id": "alert-abc123def456",
      "severity": "high",
      "metric": "session_risk_escalation",
      "session_id": "session-001",
      "message": "Session risk escalated to HIGH: 3 high-risk event(s) detected",
      "details": {
        "previous_risk": "medium",
        "current_risk": "high",
        "high_risk_count": 3,
        "cumulative_score": 5,
        "trigger_event_id": "evt-003",
        "tool_name": "bash"
      },
      "triggered_at": "2026-03-23T10:30:00+00:00",
      "acknowledged": false,
      "acknowledged_by": null,
      "acknowledged_at": null
    }
  ],
  "total_unacknowledged": 5,
  "generated_at": "2026-03-23T10:31:00+00:00",
  "window_seconds": null
}
```

### curl 示例

```bash
# 所有未确认的高风险告警
curl -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  "http://127.0.0.1:8080/report/alerts?severity=high&acknowledged=false"

# 最近 1 小时的告警
curl -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  "http://127.0.0.1:8080/report/alerts?window_seconds=3600"
```

---

## POST /report/alerts/{id}/acknowledge — 确认告警 {#post-report-alerts-acknowledge}

将指定告警标记为已确认。

### 路径参数

| 参数 | 说明 |
|------|------|
| `id` | 告警 ID |

### 请求

```json
{
  "acknowledged_by": "operator-zhang"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `acknowledged_by` | string | :material-close: | 确认者标识（默认 `"unknown"`） |

### 成功响应

```json
{
  "alert_id": "alert-abc123def456",
  "acknowledged": true,
  "acknowledged_by": "operator-zhang",
  "acknowledged_at": "2026-03-23T10:35:00+00:00"
}
```

### 告警不存在（404）

```json
{
  "error": "Alert 'alert-not-exist' not found"
}
```

### curl 示例

```bash
curl -X POST http://127.0.0.1:8080/report/alerts/alert-abc123def456/acknowledge \
  -H "Authorization: Bearer $CS_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"acknowledged_by": "operator-zhang"}'
```

---

## GET /ui — Web 仪表板 {#get-ui}

提供内置 Web 安全仪表板的静态文件服务。

| 路径 | 说明 |
|------|------|
| `GET /ui` | 仪表板首页（`index.html`） |
| `GET /ui/{path}` | SPA 路由——先查找静态文件，找不到则回退到 `index.html` |

仪表板前端使用 React 18 + TypeScript + Vite 构建，包含以下页面：

- **Dashboard** —— 实时决策 Feed + 指标卡 + 图表
- **Sessions** —— 会话列表 + D1-D5 雷达图 + 风险曲线
- **Alerts** —— 告警管理 + 过滤 + 确认
- **DEFER Panel** —— 倒计时 + Allow/Deny 按钮

!!! note "静态文件条件"
    仅当 `ui/dist/index.html` 存在时，`/ui` 路由才会注册。如果未构建前端资源，这些端点不可用。

---

## 通用错误响应

所有端点共享以下错误格式：

### 401 Unauthorized

```json
{
  "error": "Unauthorized"
}
```

响应头包含 `WWW-Authenticate: Bearer`。

### 400 Bad Request

```json
{
  "error": "window_seconds must be between 1 and 604800"
}
```

### 429 Rate Limited

```json
{
  "rpc_version": "sync_decision.1.0",
  "request_id": "rate-limited",
  "rpc_status": "error",
  "rpc_error_code": "RATE_LIMITED",
  "rpc_error_message": "Rate limit exceeded",
  "retry_eligible": true,
  "retry_after_ms": 1000
}
```

### 503 Service Unavailable

```json
{
  "error": "Too many SSE subscribers"
}
```
