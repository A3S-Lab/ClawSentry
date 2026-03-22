---
title: Web 安全仪表板
description: ClawSentry 内置 Web 仪表板，提供实时安全态势感知与交互式决策审批
---

# Web 安全仪表板

ClawSentry 内置了一个 **Web 安全仪表板 (Security Operations Dashboard)**，面向安全运维人员（SOC Analyst）提供实时安全态势感知、会话风险分析、告警管理和交互式 DEFER 决策审批。

仪表板采用深色 SOC 主题设计，视觉风格对标专业安全运营中心，在复杂监控场景下减少视觉疲劳。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript |
| 构建 | Vite |
| 图表 | recharts |
| 样式 | 纯 CSS（无 UI 框架），暗色 SOC 主题 |
| 数据 | REST API + SSE 实时推送 |
| 源码 | `src/clawsentry/ui/` |

---

## 访问方式

启动 Gateway 后，仪表板在 `/ui` 路径提供服务：

```bash
# 启动 Gateway（默认端口 8080）
clawsentry gateway
```

然后在浏览器中打开：

```
http://localhost:8080/ui
```

!!! tip "自定义端口"
    如果 Gateway 使用了自定义端口（通过 `CS_HTTP_PORT` 环境变量），请将 URL 中的 `8080` 替换为实际端口号。

---

## 认证机制

仪表板使用 **Bearer Token 认证**，与 Gateway REST API 共享同一认证体系。

### 登录流程

1. 在环境变量中设置认证令牌：
   ```bash
   export CS_AUTH_TOKEN="your-secure-token-here"
   ```
2. 启动 Gateway
3. 打开仪表板页面，输入令牌进行登录
4. 令牌存储在浏览器的 `sessionStorage` 中（关闭标签页后自动清除）

### API 请求认证

所有 REST API 请求通过 HTTP Header 携带令牌：

```
Authorization: Bearer <token>
```

### SSE 连接认证

由于浏览器原生 `EventSource` API 不支持自定义 Header，SSE 连接通过 **URL Query 参数**传递令牌：

```
/report/stream?token=<token>&types=decision,alert
```

!!! warning "安全提示"
    生产环境中务必启用 HTTPS，防止令牌在 URL 中被中间人截获。参见 [生产部署](../operations/deployment.md) 中的 SSL/TLS 配置。

---

## 页面布局

仪表板采用经典 SOC 布局：

- **左侧栏 (Sidebar)** -- 导航菜单，包含 4 个主要页面的快速跳转
- **顶部栏 (StatusBar)** -- 全局状态指示器，显示 Gateway 连接状态
- **主内容区 (Content)** -- 各页面的具体内容

导航菜单包含以下入口：

| 图标 | 页面 | 路径 | 说明 |
|------|------|------|------|
| :material-view-dashboard: | Dashboard | `/` | 主页，实时态势概览 |
| :material-account-group: | Sessions | `/sessions` | 活跃会话列表与风险分析 |
| :material-alert: | Alerts | `/alerts` | 告警工作台 |
| :material-shield-check: | DEFER Panel | `/defer` | 延迟审批交互面板 |

---

## Dashboard 主页 {#dashboard}

Dashboard 主页提供 ClawSentry 运行态势的全局概览，是安全运维人员的首选着陆页。

### 指标卡片 (Metric Cards)

页面顶部展示 4 个核心指标卡片，每 10 秒自动刷新：

| 指标 | 说明 |
|------|------|
| **Total Decisions** | 决策总数，反映系统整体吞吐量 |
| **Block Rate** | 拦截率（Block 数量 / 总决策数），以百分比展示 |
| **Risk Levels** | 当前出现过的风险等级种类数 |
| **Sources** | 已接入的 Agent 框架数量（如 a3s-code, openclaw） |

### 实时决策流 (Decision Feed)

位于页面中部左侧，以实时列表形式展示最近的决策记录。每条记录包含：

- 时间戳
- 决策结果（ALLOW / BLOCK / DEFER / MODIFY）
- 风险等级（LOW / MEDIUM / HIGH / CRITICAL）
- 工具名称
- 决策延迟（毫秒级）

数据通过 SSE 实时推送，新决策在产生时立即显示在列表顶部，无需手动刷新。

### 风险分布饼图 (PieChart)

位于页面中部右侧，以环形饼图展示决策的风险等级分布：

- **绿色** (`#3fb950`) -- LOW
- **黄色** (`#d29922`) -- MEDIUM
- **橙色** (`#db6d28`) -- HIGH
- **红色** (`#f85149`) -- CRITICAL

每个扇区标注百分比，鼠标悬停显示具体数值。

### 判决柱状图 (BarChart)

页面底部并排展示两个柱状图：

**Decisions by Verdict** -- 按判决类型统计：

- Allow（绿色）
- Block（红色）
- Defer（黄色）
- Modify（蓝色）

**Decisions by Source** -- 按来源框架统计，显示各 Agent 框架贡献的事件数量。

---

## Sessions 会话页 {#sessions}

Sessions 页面提供对所有活跃 Agent 会话的监控和深度分析能力。

### 会话列表

以表格形式展示所有活跃会话，每 15 秒自动刷新。列包含：

| 列名 | 说明 |
|------|------|
| **Session ID** | 会话标识符，可点击进入详情视图 |
| **Agent** | Agent 标识符 |
| **Risk** | 当前风险等级，以彩色徽章展示 |
| **Events** | 会话内事件总数 |
| **Source** | 来源框架（a3s-code / openclaw） |
| **Last Activity** | 最后活动时间 |

#### 过滤与排序

- **风险等级过滤** -- 下拉框选择最低风险等级（Low+ / Medium+ / High+ / Critical）
- **默认排序** -- 按风险等级降序（`risk_desc`），高风险会话置顶
- **手动刷新** -- 点击刷新按钮立即更新数据

### 会话详情视图 (Session Detail) {#session-detail}

点击会话 ID 进入详情页面，提供该会话的完整安全分析视图。

#### D1-D5 雷达图 (Radar Chart)

以雷达图可视化会话最新的五维风险评分：

| 维度 | 含义 | 取值范围 |
|------|------|----------|
| **D1: Tool Risk** | 工具类型危险性 | 0-3 |
| **D2: Target Sensitivity** | 目标路径敏感度 | 0-3 |
| **D3: Data Flow** | 命令模式危险性 | 0-3 |
| **D4: Frequency** | 上下文风险累积 | 0-2 |
| **D5: Context** | Agent 信任等级 | 0-2 |

雷达图使用蓝色填充，透明度 20%，直观展示各维度的风险分布形态。

#### 会话元数据

右侧面板展示关键会话指标：

- **Cumulative Score** -- 累积风险评分
- **Tools Used** -- 会话中使用过的所有工具列表
- **Risk Hints** -- 出现过的风险提示标签（如 `shell_execution`、`destructive_pattern`）
- **Tier Distribution** -- L1/L2 决策层级分布

#### 风险曲线 (Risk Curve)

以折线图展示会话风险评分随时间的变化趋势：

- X 轴为时间
- Y 轴为归一化后的综合评分（0-1 范围）
- 蓝色折线，关键拐点以圆点标注

通过风险曲线可以快速识别风险骤升的时间节点。

#### 决策时间线 (Decision Timeline)

以时间线形式按时间顺序展示会话内所有决策记录：

- 每条记录包含时间戳、决策结果徽章、风险等级徽章、工具名称、决策原因和延迟
- 可滚动浏览完整轨迹
- 最多展示 400px 高度的可滚动区域

---

## Alerts 告警页 {#alerts}

Alerts 页面是一个完整的告警工作台，支持告警查看、过滤、确认和实时推送。

### 告警表格

以表格形式展示所有告警，每 30 秒自动刷新。列包含：

| 列名 | 说明 |
|------|------|
| **Severity** | 严重程度：`info` / `warning` / `critical` |
| **Metric** | 触发告警的指标名称 |
| **Session** | 关联的会话 ID，可点击跳转到会话详情 |
| **Message** | 告警消息内容 |
| **Triggered** | 告警触发时间 |
| **Status** | 状态：OPEN（未确认）或 ACK（已确认） |
| **操作** | 未确认的告警显示 Acknowledge 按钮 |

### 过滤器

支持两个维度的过滤，可组合使用：

- **严重程度过滤** -- 下拉框选择 `Info` / `Warning` / `Critical`
- **状态过滤** -- 下拉框选择 `Unacknowledged` / `Acknowledged`

### 确认操作

点击 **Acknowledge** 按钮将告警标记为已处理。已确认的告警：

- 以 50% 透明度显示，视觉上降低优先级
- 状态列显示绿色 :material-check-circle: ACK 标记
- Acknowledge 按钮隐藏

### SSE 实时推送

告警页面自动建立 SSE 连接，订阅 `alert` 事件类型。当新告警产生时：

- 新告警立即插入到表格顶部
- 无需手动刷新或轮询
- 浏览器标签页在后台时也能接收

```typescript
// SSE 连接示例（前端自动处理）
const es = connectSSE(['alert'])
es.addEventListener('alert', (e: MessageEvent) => {
  const data = JSON.parse(e.data)
  // 新告警自动添加到列表顶部
})
```

---

## DEFER Panel 延迟审批页 {#defer-panel}

DEFER Panel 是 ClawSentry 最具交互性的页面，允许运维人员在 Web 界面上实时审批或拒绝 DEFER 决策。

### 工作原理

当策略引擎对某个 Agent 操作做出 DEFER 决策时：

1. 决策通过 SSE 实时推送到 DEFER Panel
2. 运维人员在倒计时结束前做出 Allow 或 Deny 决定
3. 决策通过 `POST /ahp/resolve` 代理到 OpenClaw Gateway 执行

### 待处理区域 (Pending)

显示所有等待审批的 DEFER 决策，每条记录包含：

- **工具名称** -- 请求执行的工具
- **风险等级徽章** -- LOW / MEDIUM / HIGH / CRITICAL
- **命令内容** -- 具体请求执行的命令，以代码样式展示
- **决策原因** -- 策略引擎给出的决策理由
- **倒计时器** -- 显示剩余审批时间
- **操作按钮**:
    - **Allow** -- 允许此次操作（绿色按钮）
    - **Deny** -- 拒绝此次操作（红色按钮）

```
┌─────────────────────────────────────────────────────────┐
│  bash          ⚠ MEDIUM                    ⏱ 00:42     │
│  ┌─────────────────────────────────────────────┐       │
│  │ rm -rf /tmp/old-cache                       │       │
│  └─────────────────────────────────────────────┘       │
│  Medium risk: allowed with audit | D1=2 ...  [Allow] [Deny] │
└─────────────────────────────────────────────────────────┘
```

### 已处理区域 (Resolved)

显示已经处理过的决策，每条记录包含：

- 状态徽章：ALLOWED（绿色）/ DENIED（红色）/ EXPIRED（黄色）
- 工具名称和命令摘要
- 处理时间

已处理的记录以 50% 透明度显示，降低视觉干扰。

### 倒计时超时处理

如果运维人员未在倒计时结束前做出决定：

- 记录自动标记为 **EXPIRED** 状态
- 从待处理区域移到已处理区域
- Agent 端根据框架配置执行超时行为（通常为拒绝）

### 503 降级提示

当 OpenClaw 未连接或不可用时：

- 页面顶部显示黄色警告横幅：*"Resolve not available -- OpenClaw enforcement is not connected"*
- Allow / Deny 按钮变为禁用状态
- 运维人员仍可查看 DEFER 决策的详情，但无法执行审批操作

!!! info "关于 DEFER 审批的替代方式"
    除 Web 仪表板外，你还可以通过 CLI 进行交互式审批：
    ```bash
    clawsentry watch --interactive
    ```
    CLI 方式支持键盘快捷键 `[A]llow / [D]eny / [S]kip`，适合终端工作流场景。

---

## SSE 事件类型

仪表板通过 SSE 订阅以下事件类型：

| 事件类型 | 订阅页面 | 说明 |
|----------|----------|------|
| `decision` | Dashboard, DEFER Panel | 每个决策结果实时广播，包含 reason / command / approval_id / expires_at |
| `alert` | Alerts | 新告警通知 |
| `session_start` | Sessions | 新会话开始 |
| `session_risk_change` | Sessions | 会话风险等级变化 |
| `session_enforcement_change` | Sessions | 会话执法状态变化（强制 DEFER/BLOCK） |

### 连接参数

SSE 端点支持以下 Query 参数：

```
GET /report/stream?token=<token>&types=decision,alert&session_id=<id>&min_risk=<level>
```

| 参数 | 说明 |
|------|------|
| `token` | 认证令牌（必须，当启用认证时） |
| `types` | 订阅的事件类型，逗号分隔 |
| `session_id` | 只接收指定会话的事件 |
| `min_risk` | 最低风险等级过滤 |

---

## 前端开发

如果你需要修改仪表板前端代码：

### 源码结构

```
src/clawsentry/ui/
├── src/
│   ├── api/
│   │   ├── client.ts        # API 客户端，认证逻辑
│   │   ├── sse.ts           # SSE 连接工具
│   │   └── types.ts         # TypeScript 类型定义
│   ├── components/
│   │   ├── Layout.tsx        # 主布局（侧边栏 + 顶栏 + 内容区）
│   │   ├── StatusBar.tsx     # 顶部状态栏
│   │   ├── MetricCard.tsx    # 指标卡片组件
│   │   ├── DecisionFeed.tsx  # 实时决策流组件
│   │   ├── CountdownTimer.tsx # 倒计时器组件
│   │   ├── LoginForm.tsx     # 登录表单
│   │   └── badges.tsx        # 风险/决策徽章组件
│   ├── hooks/
│   │   └── useAuth.ts       # 认证状态 Hook
│   ├── pages/
│   │   ├── Dashboard.tsx    # 主页
│   │   ├── Sessions.tsx     # 会话列表
│   │   ├── SessionDetail.tsx # 会话详情
│   │   ├── Alerts.tsx       # 告警工作台
│   │   └── DeferPanel.tsx   # DEFER 审批面板
│   ├── App.tsx              # 路由配置
│   └── main.tsx             # 入口文件
├── package.json
├── vite.config.ts
└── dist/                    # 构建产物（已追踪到 Git）
```

### 本地开发

```bash
cd src/clawsentry/ui
npm install
npm run dev
```

!!! note "开发模式代理"
    本地开发时，Vite 开发服务器需要配置代理将 API 请求转发到运行中的 Gateway。

### 构建与打包

构建产物输出到 `dist/` 目录，并通过 `pyproject.toml` 配置包含在 Python 包中：

```bash
cd src/clawsentry/ui
npm run build
```

Gateway 在启动时自动挂载 `ui/dist/` 为静态文件目录，并配置 SPA fallback（所有未匹配的路径返回 `index.html`）。
