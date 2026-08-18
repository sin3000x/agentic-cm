# Agentic Case Management

一个面向供应链异常处置的 Case 驱动、多角色、多 Agent 协同平台 demo。

本项目的核心目标不是让 Agent 直接修改业务系统，而是展示如何把跨组织异常处置组织成一个可审查、可追责、可复盘的决策过程：

> Agent 负责理解、提案和推演；人负责专业承诺与最终决定；平台负责状态、依赖和审计。

## 设计文档

- [产品目标、术语与系统架构](docs/01-product-architecture.md)
- [领域模型、状态机与 CommitmentDAG](docs/02-domain-lifecycle.md)
- [Agent Adapter 契约](docs/03-agent-adapter-contract.md)
- [Demo 剧情与 MVP 验收标准](docs/04-demo-acceptance.md)

当前仓库只包含设计基线，尚未进入业务代码实现阶段。
