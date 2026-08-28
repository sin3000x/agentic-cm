# 产品目标与系统架构

## 产品定位

供应链异常协同 demo。首个完整闭环是订单延期 Case 上的物料替代 Path。

治理主线：

- Agent 分析、提案、推演；
- 人做专业承诺和最终决定；
- 平台拥有 Case 状态、依赖和审计。

Agent 不能伪造承诺、绕过强制 Policy，或修改 ERP / 库存 / 订单系统。首版“执行”只指 Path 探索和只读 sandbox 查询。

## 实际代码结构

这是单进程、SQLite 的 Python 模块化单体，外加 React 工作台。没有独立 Policy Engine、Audit Service、消息队列或 Agent 框架控制面。

```text
Web UI  ──HTTP──►  FastAPI (api.py)
                      │
                      ▼
                 CaseService
            ┌─────┼──────┬──────────┐
            ▼     ▼      ▼          ▼
      Orchestrator  PathAgent  SynthesisAgent  CapabilityRegistry
            │         │          │
            └─────────┴──────────┘
                      ▼
              CaseRepository (SQLite JSON + domain_events + agent_runs)
```

模块就是这些文件，不是文档里曾经列出的九个包。

## 权威状态

- Case 当前状态是 SQLite `cases.payload` 里的一份 `Case` JSON。
- 业务事件追加到 `domain_events`，同一事务写入。
- Agent 运行记录在 `agent_runs` / `agent_trace_events`。失败 run 保留 trace，不改 Case。
- Capability 以目录文件为源，Manifest 只冻结 `id/version/digest`。
