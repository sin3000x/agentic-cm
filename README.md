# Agentic Case Management

一个面向供应链异常处置的 Case 驱动、多角色、多 Agent 协同平台 demo。

本项目的核心目标不是让 Agent 直接修改业务系统，而是展示如何把跨组织异常处置组织成一个可审查、可追责、可复盘的决策过程：

> Agent 负责理解、提案和推演；人负责专业承诺与最终决定；平台负责状态、依赖和审计。

## 设计文档

- [产品目标、术语与系统架构](docs/01-product-architecture.md)
- [领域模型、状态机与 CommitmentDAG](docs/02-domain-lifecycle.md)
- [Agent Adapter 契约](docs/03-agent-adapter-contract.md)
- [Demo 剧情与 MVP 验收标准](docs/04-demo-acceptance.md)

## 初版实现

当前仓库包含一个刻意收敛的首版框架：

- `backend/agentic_cm`：Python 模块化单体，领域对象、SQLite Repository、Case Service 与 FastAPI；
- `frontend`：React + TypeScript 工作台，使用 Vite 驱动的 vinext 构建；
- `tests`：Manifest 批准、并行节点开放和安全 Reset 的领域测试。

首个可运行切片只覆盖：查看订单延期 Case、审查 Manifest、Owner 批准 Path，以及创建包含主计划/研发并行节点的 CommitmentDAG。后续审批、修订、局部重审和最终关闭仍按验收文档逐步补齐。

### 本地启动

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m uvicorn agentic_cm.api:app --app-dir backend --reload --port 8000
```

另开终端：

```bash
cd frontend
npm ci
npm run dev
```

打开 `http://localhost:3000`。API 文档位于 `http://localhost:8000/docs`。

### 技术选择

前端采用 React + TypeScript：审批 DAG、角色切换和方案修订需要明确的交互状态，React 足够直接；首版不引入额外状态管理、通用 DAG 编辑器或组件平台。后端保持 Python 单体与标准 SQLite，Agent Adapter 仍是可替换边界，不进入领域层。
