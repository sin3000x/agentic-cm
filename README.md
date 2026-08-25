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
- [Orchestrator 架构、兼容模型接入与验收](docs/06-orchestrator.md)

## 初版实现

当前仓库包含一个刻意收敛的首版框架：

- `backend/agentic_cm`：Python 模块化单体，领域对象、SQLite Repository、Case Service 与 FastAPI；
- `capabilities/builtin`：可版本化的 Policy、Skill 与 Knowledge 默认资产；
- `frontend`：React + TypeScript 工作台，使用 Vite 驱动的 vinext 构建；
- `tests`：Manifest 能力快照、Policy 编译、并行节点、本地资产覆盖和安全 Reset 的领域测试。

首个可运行切片覆盖：从 `INTAKE` 的订单延期 Case 触发 Orchestrator、由命中的 `ORDER_DELIVERY_RISK` 编排 Skill 提供提拉/替代/拆分三条 Path、逐 Path 匹配执行 Skill 与 Policy 并冻结能力快照，以及由 Owner 在前端单选或多选本轮探索子集。不同 `case_type` 命中各自拥有 `paths.json` 的编排 Skill。Demo 默认只勾选“替代”，批准后平台只为获批 Path 创建 PathAttempt 与 Commitment 节点；后续审批、修订、局部重审和最终关闭仍按验收文档逐步补齐。

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

### 使用兼容模型规划 Manifest

项目启动时会自动读取根目录 `.env`，但不会覆盖终端中已经存在的环境变量。先复制示例：

```bash
cp .env.example .env
```

不配置模型时使用可复现的 deterministic Planner。需要使用模型时，在 `.env` 中填写：

```dotenv
AGENTIC_CM_ADAPTER=openai-compatible
AGENTIC_CM_LLM_BASE_URL=https://your-provider.example/v1
AGENTIC_CM_LLM_API_KEY=your-key
AGENTIC_CM_LLM_MODEL=your-model-id
AGENTIC_CM_PATH_MAX_OUTPUT_TOKENS=6000
AGENTIC_CM_SYNTHESIS_MAX_OUTPUT_TOKENS=4000
```

然后正常启动，无需额外 `export`：

```bash
.venv/bin/python -m uvicorn agentic_cm.api:app --app-dir backend --reload --port 8000
```

不要把 Key 写入仓库、Capability 文件或 Case payload。具体请求链与失败边界见 [Orchestrator 实现](docs/06-orchestrator.md)。

### 生成并检查 Manifest

将 Demo 恢复到 `INTAKE`，调用 Orchestrator，再单独读取 Manifest：

```bash
curl -sS -X POST http://localhost:8000/api/demo/reset \
  -H 'Content-Type: application/json' \
  -d '{"dataset_id":"supply-chain-golden-path-v1"}'
curl -sS -X POST http://localhost:8000/api/cases/CM-2026-014/orchestrate \
  -H 'Content-Type: application/json' \
  -d '{"actor":"陈澄","role":"订单统筹经理"}'
curl -sS 'http://localhost:8000/api/cases/CM-2026-014/manifest?actor=陈澄&role=订单统筹经理' \
  | python3 -m json.tool
```

也可以打开前端，点击“生成 Manifest”，然后查看 Path、Planner profile 与冻结的 Policy/Skill/Knowledge 能力快照。

Case Owner 还可以在同一工作台展开“Orchestrator Trace”，查看本次运行从 Case 门禁、候选 Path 与能力解析，到模型请求/响应、输出校验和 Manifest 持久化的每一步。失败运行同样保留 trace，但不会修改 Case。也可以直接调用：

```bash
curl -sS 'http://localhost:8000/api/cases/CM-2026-014/agent-runs?actor=陈澄&role=订单统筹经理&agent_type=orchestrator' \
  | python3 -m json.tool
```

Path Agent trace 已实现：方案生成后可在对应 SolutionRevision 下按 Path 展开，默认折叠；Synthesis Agent trace 尚未实现。详见 [Orchestrator 实现](docs/06-orchestrator.md)。

当 Manifest 含多条 Path 时，每条 Path 都有独立的 `capability_snapshots[path_id]`。可以单独检查：

```bash
curl -sS 'http://localhost:8000/api/cases/CM-2026-014/capabilities?actor=陈澄&role=订单统筹经理&path_id=PATH-02' \
  | python3 -m json.tool
```

Manifest、能力快照、生成和审批仅 Case Owner 可访问；其他身份读取 Case 时 `manifest` 会被脱敏为 `null`。这里的 `actor` / `role` 是 Demo 身份模拟，生产环境必须由可信认证层注入，不能信任客户端自报身份。
