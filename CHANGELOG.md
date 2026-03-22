# Changelog

本文件记录 ClawSentry 各版本的重要变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.1.0] — 2026-03-23

首个公开版本。ClawSentry 是 Agent Harness Protocol (AHP) 的 Python 参考实现——一个面向 AI Agent 运行时的统一安全监督网关，支持 a3s-code 和 OpenClaw 双框架接入。

### 新增

#### 核心架构
- 实现 AHP (Agent Harness Protocol) 统一协议规范，归一化多框架运行时事件
- Sidecar 架构 + UDS（主传输）+ HTTP（备传输）双通道入口
- 同步阻塞 `pre_action` + 异步审计 `post_action` 双通道处理
- 基于 Pydantic v2 的 CanonicalEvent / CanonicalDecision 协议模型
- JSON-RPC 2.0 同步决策接口 (`sync_decision.1.0`)

#### 三层决策模型
- **L1 规则引擎** (<1ms)：D1-D5 五维风险评分（命令危险度/参数敏感度/上下文合理性/历史行为/作用域权限）
- **L2 语义分析** (<3s)：SemanticAnalyzer Protocol + RuleBased / LLM / Composite 三种实现
- **L3 审查 Agent** (<30s)：AgentAnalyzer + ReadOnlyToolkit + SkillRegistry + 多轮工具调用推理
- L3 推理轨迹持久化到 TrajectoryStore (`l3_trace_json` 列)

#### 框架适配器
- **a3s-code Adapter**：stdio harness + HTTP Transport (`POST /ahp/a3s`) 双模式
- **OpenClaw Adapter**：WebSocket 实时事件监听 + Webhook 接收器 + 审批执行器
- LLM 工厂：环境变量驱动的 Anthropic/OpenAI/自定义 provider 构建

#### 安全加固
- Bearer Token HTTP 认证 (`CS_AUTH_TOKEN`)
- Webhook HMAC-SHA256 签名验证 + IP 白名单 + Token TTL
- UDS socket `chmod 0o600` 权限保护
- SSL/TLS 支持 (`AHP_SSL_CERTFILE` / `AHP_SSL_KEYFILE`)
- 速率限制 (`CS_RATE_LIMIT_PER_MINUTE`，默认 300/分钟)
- 幂等性缓存防重复决策
- 按风险等级分层的重试预算（CRITICAL/HIGH=1, MEDIUM=2, LOW=3）

#### 会话管理
- SessionRegistry：会话生命周期追踪 + 风险累积
- 会话级强制策略 (SessionEnforcementPolicy)：累积 N 次高危后自动 DEFER/BLOCK/L3
- 冷却期自动释放 + 手动释放 REST API

#### 实时监控
- EventBus：进程内事件广播
- SSE 实时推送：decision / session_start / session_risk_change / alert / session_enforcement_change
- AlertRegistry：告警聚合 + 过滤 + 确认
- `clawsentry watch` CLI：终端实时展示（彩色输出/JSON 模式/事件过滤）
- `clawsentry watch --interactive`：DEFER 运维确认 (Allow/Deny/Skip + 超时安全余量)

#### Web 安全仪表板
- React 18 + TypeScript + Vite SPA，暗色 SOC 主题
- Dashboard：实时决策 feed + 指标卡 + 饼图/柱状图
- Sessions：会话列表 + D1-D5 雷达图 + 风险曲线 + 决策时间线
- Alerts：告警表格 + 过滤 + 确认 + SSE 自动推送
- DEFER Panel：倒计时 + Allow/Deny 按钮 + 503 降级提示
- Gateway 在 `/ui` 路径提供静态文件 + SPA fallback

#### CLI 工具
- `clawsentry init <framework>`：零配置初始化（支持 `--auto-detect` / `--setup` / `--dry-run`）
- `clawsentry gateway`：智能启动（自动检测 OpenClaw 配置，按需启用 Webhook/WS）
- `clawsentry harness`：a3s-code stdio harness
- `clawsentry watch`：SSE 实时监控
- `.env` 文件自动加载（dotenv_loader）

#### REST API
- `POST /ahp` — OpenClaw Webhook 决策端点
- `POST /ahp/a3s` — a3s-code HTTP Transport
- `POST /ahp/resolve` — DEFER 决策代理 (allow-once/deny)
- `GET /health` — 健康检查
- `GET /report/summary` — 跨框架聚合统计
- `GET /report/stream` — SSE 实时推送（支持 `?token=` query param 认证）
- `GET /report/sessions` — 活跃会话列表 + 风险排序
- `GET /report/session/{id}` — 会话轨迹回放
- `GET /report/session/{id}/risk` — 会话风险详情 + 时间线
- `GET /report/session/{id}/enforcement` — 会话执法状态查询
- `POST /report/session/{id}/enforcement` — 会话执法手动释放
- `GET /report/alerts` — 告警列表 + 过滤
- `POST /report/alerts/{id}/acknowledge` — 确认告警

#### L3 Skills
- 6 个内置审查技能：shell-audit / credential-audit / code-review / file-system-audit / network-audit / general-review
- 自定义 Skills 支持 (`AHP_SKILLS_DIR` 环境变量)
- Skills Schema：enabled / priority 字段 + 双语 system_prompt + 扩展 triggers

#### 测试
- 775 个测试用例，覆盖单元测试 + 集成测试 + E2E 测试
- 测试通过时间 ~6.5s

[0.1.0]: https://github.com/Elroyper/ClawSentry/releases/tag/v0.1.0
