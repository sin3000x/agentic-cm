# Agentic Case Management

一个面向供应链异常处置的 Case 驱动、多角色、多 Agent 协同平台 demo。

本项目的核心目标不是让 Agent 直接修改业务系统，而是展示如何把跨组织异常处置组织成一个可审查、可追责、可复盘的决策过程：

> Agent 负责理解、提案和推演；人负责专业承诺与最终决定；平台负责状态、依赖和审计。

## 设计文档

- [产品目标、术语与系统架构](docs/01-product-architecture.md)
- [领域模型、状态机与 CommitmentDAG](docs/02-domain-lifecycle.md)
- [Agent Adapter 契约](docs/03-agent-adapter-contract.md)
- [Demo 剧情与 MVP 验收标准](docs/04-demo-acceptance.md)
- [初版能力底座：Policy、Skill 与 Knowledge](docs/05-capability-foundation.md)

## 初版实现

当前仓库包含一个刻意收敛的首版框架：

- `backend/agentic_cm`：Python 模块化单体，领域对象、SQLite Repository、Case Service 与 FastAPI；
- `capabilities/builtin`：可版本化的 Policy、Skill 与 Knowledge 默认资产；
- `frontend`：React + TypeScript 工作台，使用 Vite 驱动的 vinext 构建；
- `tests`：Manifest 能力快照、Policy 编译、并行节点、本地资产覆盖和安全 Reset 的领域测试。

首个可运行切片覆盖：查看订单延期 Case、审查 Manifest 与冻结的能力快照、Owner 批准 Path，以及按编译后的 Policy 创建包含主计划/研发并行节点的 CommitmentDAG。后续审批、修订、局部重审和最终关闭仍按验收文档逐步补齐。

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

前端默认监听 `127.0.0.1:3000`，可在 `frontend/.env.local` 中通过 `AGENTIC_CM_WEB_HOST` 和 `AGENTIC_CM_WEB_PORT` 修改。API 文档位于 `http://localhost:8000/docs`。

### 接入自己的本地能力

`.agentic-cm/capabilities/` 是不入仓的本地扩展层。开发者可以新增任意自己的 Skill、Policy 和 Knowledge，不需要复制或采用仓库中的文件名：

```bash
mkdir -p .agentic-cm/capabilities
cp -R examples/local-capabilities/. .agentic-cm/capabilities/
PYTHONPATH=backend .venv/bin/python -m agentic_cm.capabilities validate
```

详细契约与替换规则见[能力底座文档](docs/05-capability-foundation.md)。

### 技术选择

前端采用 React + TypeScript：审批 DAG、角色切换和方案修订需要明确的交互状态，React 足够直接；首版不引入额外状态管理、通用 DAG 编辑器或组件平台。后端保持 Python 单体与标准 SQLite，Agent Adapter 仍是可替换边界，不进入领域层。
