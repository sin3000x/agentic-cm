# Agentic Case Management

一个面向供应链异常处置的 Case 驱动、多角色、多 Agent 协同平台 demo。

本项目的核心目标不是让 Agent 直接修改业务系统，而是展示如何把跨组织异常处置组织成一个可审查、可追责、可复盘的决策过程：

> Agent 负责理解、提案和推演；人负责专业承诺与最终决定；平台负责状态、依赖和审计。

## 设计文档

- [代码地图](docs/code-map.md)
- [产品目标与系统架构](docs/01-product-architecture.md)
- [领域模型与状态机](docs/02-domain-lifecycle.md)
- [Agent Adapter 契约](docs/03-agent-adapter-contract.md)
- [Demo 与验收](docs/04-demo-acceptance.md)
- [能力底座](docs/05-capability-foundation.md)

## 初版实现

当前仓库包含一个刻意收敛的首版框架：

- `backend/agentic_cm`：Python 模块化单体，领域对象、SQLite Repository、Case Service 与 FastAPI；
- `capabilities/builtin`：可版本化的 Policy、Skill 与 Knowledge 默认资产；
- `frontend`：React + TypeScript 工作台，使用 Vite 驱动的 vinext 构建；
- `tests`：Manifest 能力快照、Policy 编译、并行节点、本地资产覆盖和安全 Reset 的领域测试。

首个可运行切片覆盖：从 `INTAKE` 的订单延期 Case 触发 Orchestrator、按 Case Type Catalog 展开提拉/替代/拆分三条 Path、按 `case_type + path_definition` 确定性匹配 Policy，并由 Orchestrator 从轻量 Skill Catalog 自主选择入口后冻结 Bundle 展开结果。Owner 在前端单选或多选本轮探索子集。Skill 不再绑定 Case Type 或 Path；组织资产页按维护 Role 分组。Demo 默认只勾选“替代”，批准后平台只为获批 Path 创建 PathAttempt 与 Commitment 节点。

### 本地验证

安装后端开发依赖和前端依赖后，在仓库根目录运行：

```bash
make check
```

依次执行后端测试、能力目录校验、前端 lint、TypeScript 检查，以及一次构建和页面渲染测试；任何一步失败即停止。验证使用本地测试模型，不调用真实 LLM。

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

不配置模型时使用可复现的 deterministic Adapter。

deterministic 模式下，Orchestrator、每个 Path Agent 和 Synthesis Agent 默认都会异步等待 3 秒，以便在演示中呈现 Agent 工作过程。可在 `.env` 中调整，设为 `0` 可关闭模拟延迟：

```dotenv
AGENTIC_CM_DETERMINISTIC_DELAY_SECONDS=3
```

该设置不影响 `openai-compatible` 模式；并行 Path 的等待也会并行发生。

需要使用模型时，在 `.env` 中填写：

```dotenv
AGENTIC_CM_ADAPTER=openai-compatible
AGENTIC_CM_LLM_BASE_URL=https://your-provider.example/v1
AGENTIC_CM_LLM_API_KEY=your-key
AGENTIC_CM_LLM_MODEL=your-model-id
AGENTIC_CM_PATH_MAX_OUTPUT_TOKENS=6000
AGENTIC_CM_SYNTHESIS_MAX_OUTPUT_TOKENS=4000
```

推理模型需要把思考时间和思考 token 纳入预算。三个 Agent 的单次请求默认超时为 45 秒，token 默认值分别是 Orchestrator 800、Path 6000、Synthesis 4000；现在均可配置。对于 GLM-5.3，可先使用以下配置，再根据实际耗时调整：

```dotenv
AGENTIC_CM_LLM_TIMEOUT_SECONDS=300
AGENTIC_CM_ORCHESTRATOR_MAX_OUTPUT_TOKENS=32768
AGENTIC_CM_PATH_MAX_OUTPUT_TOKENS=32768
AGENTIC_CM_SYNTHESIS_MAX_OUTPUT_TOKENS=32768
AGENTIC_CM_LLM_THINKING_ENABLED=true
AGENTIC_CM_LLM_REASONING_EFFORT=low
```

也可使用 `AGENTIC_CM_LLM_MAX_OUTPUT_TOKENS` 作为公共预算；各 Agent 的 `*_MAX_OUTPUT_TOKENS` 优先，因此使用公共值时需删除已有的单独预算。超时可分别通过 `AGENTIC_CM_ORCHESTRATOR_LLM_TIMEOUT_SECONDS`、`AGENTIC_CM_PATH_LLM_TIMEOUT_SECONDS` 和 `AGENTIC_CM_SYNTHESIS_LLM_TIMEOUT_SECONDS` 覆盖。token 预算设为 `0` 时不发送上限参数，超时设为 `0` 时关闭本地 SDK 超时；模型服务与代理仍可限制输出和等待时间。不发送 token 上限时，服务默认值可能仍较小。以上均为单次请求设置，Path 的多轮工具调用和重试可能增加总耗时。修改 `.env` 后重启后端。

[GLM-5.3 官方说明](https://docs.z.ai/guides/llm/glm-5.3)明确该模型始终推理，只接受 `low / high / max`。本项目不根据模型 ID 猜测能力，也不会自动改写思考开关；即使服务商将模型命名为 `glm53` 或其他别名，也统一使用上述显式配置。各 Agent 的 `*_THINKING_ENABLED` 和 `*_REASONING_EFFORT` 优先于全局值，已有单独配置时需同步调整或删除。前台选择模型只改变模型 ID，仍沿用后端的思考配置。其他模型能否关闭思考由服务商决定，`thinking.type=disabled` 不能保证所有兼容接口都执行。较大的预算允许模型完成思考，但不保证一定产出有效结果。

左侧栏的「Agent 运行模式」可统一切换三个 Agent 的 `deterministic` / `openai-compatible` 模式。首次启动的默认值来自 `AGENTIC_CM_ADAPTER`，前端选择保存到 SQLite 并全局生效；页面刷新及后端重启后保留已选模式。OpenAI-compatible 模式使用后端的 `AGENTIC_CM_LLM_BASE_URL`、`AGENTIC_CM_LLM_MODEL` 和 `AGENTIC_CM_LLM_API_KEY`（未在前台选择模型时保留各 Agent 的 model 覆盖配置）；密钥不会返回前端。OpenAI-compatible 模式下可通过「Agent 模型」选择模型，列表由后端 `/api/models` 请求模型服务的 `/models` 获取，支持刷新。前台选中的模型统一覆盖三类 Agent 的模型并保存到 SQLite，后端重启后仍生效；连接、密钥和思考配置仍使用后端配置。Agent 运行期间不能切换模式或模型。


多条已选 Path 默认并行推演。若模型服务需要限流或本地调试需要确定顺序，可在同一个 `.env` 中切换为串行：

```dotenv
AGENTIC_CM_PATH_EXECUTION_MODE=serial
```

并行模式默认最多同时运行 4 个 Path Agent，可按模型服务限流与本机资源调整：

```dotenv
AGENTIC_CM_PATH_MAX_CONCURRENCY=4
```

然后正常启动，无需额外 `export`：

```bash
.venv/bin/python -m uvicorn agentic_cm.api:app --app-dir backend --reload --port 8000
```

不要把 Key 写入仓库、Capability 文件或 Case payload。请求链与失败边界见 [Agent Adapter 契约](docs/03-agent-adapter-contract.md)。

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

Path Agent 与 Synthesis Agent 的 trace 分别挂在对应 SolutionRevision 和汇总报告下。能力快照按 Path 现算，不存在 Case 上：

```bash
curl -sS 'http://localhost:8000/api/cases/CM-2026-014/capabilities?actor=陈澄&role=订单统筹经理&path_id=PATH-02' \
  | python3 -m json.tool
```

Manifest、能力快照、生成和审批仅 Case Owner 可访问；其他身份读取 Case 时 `manifest` 会被脱敏为 `null`。这里的 `actor` / `role` 是 Demo 身份模拟，生产环境必须由可信认证层注入，不能信任客户端自报身份。
