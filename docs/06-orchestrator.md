# Orchestrator 实现

## 1. 架构选择

首版使用“确定性平台内核 + 窄 Planner Adapter”，不采用 LangGraph、Deep Agents 等框架作为平台骨架。

```text
OPEN Case (INTAKE)
  -> CapabilityRegistry 匹配 Case-level orchestration Skill
  -> 从该 Skill 包的 paths.json 读取本 case_type 的 1..N 个 PathDefinition
  -> CapabilityRegistry 要求每条 Path 同时命中 execution Skill 与强制 Policy
  -> 为每个 Path 匹配全部 Policy / Skill / Knowledge
  -> PolicyCompiler 确定性编译强制 Commitment
  -> PlannerAdapter 只能选择候选 definition 并生成 rationale
  -> Orchestrator 重新校验候选 ID，冻结 capability snapshot
  -> versioned Manifest (MANIFEST_REVIEW)
  -> Owner approve
  -> 按 frozen compiled_policy 创建 CommitmentDAG
```

模型只负责受限的语义选择与解释。Case 状态机、Path 白名单、Policy 匹配/编译、Manifest 版本与持久化均由平台掌握。因此，接入不同 Agent 框架时不需要迁移 Case 权威状态，也不会让框架 checkpoint 成为业务数据库。

## 2. 主要边界

- `CapabilityRegistry`：先通过 binding 按 `case_type` 匹配 orchestration Skill，再从该 Skill 包的 `paths.json` 展开可探索 Path。Path 定义没有第二份 catalog。
- `Path-level execution Skill`：定义获批 Path 如何分析以及 SolutionRevision 的输出结构。任一声明 Path 缺少 execution Skill 或强制 Policy 时，本次编排整体 fail closed。
- `Policy`：定义强制责任节点与依赖，不负责说明 Agent 如何分析。
- `PlannerAdapter`：异步 `propose(context, candidates) -> ManifestDraftResult`。读取命中 Skill 的说明，为 Skill 声明的每条 Path 返回 rationale 并可按相关性排序，但不能省略候选。
- `Orchestrator`：验证 Planner 输出，为每个选中 Path 冻结独立能力快照；失败时不修改 Case、不写业务事件。
- `CaseService`：成功后才保存 `manifest.proposed` 事件并将 Case 推进至 `MANIFEST_REVIEW`。
- `AgentRun trace`：每次调用先创建独立技术运行记录，逐步写入 eligibility、Path 发现、逐 Path 能力解析、Planner 输入、模型请求/响应、白名单校验、Manifest 组装和最终状态。失败 trace 也会保留，但不写业务事件、不修改 Case。

当前内置的 `shortage-response-planning/paths.json` 声明三条候选：`SupplyExpediting`（提拉）、`MaterialSubstitution`（替代）、`OrderSplit`（拆分），因此 Manifest 必须包含三条。Owner 在 Manifest Review 中单选或多选本轮探索子集；批准后平台只为勾选的 Path 创建 PathAttempt 和 Commitment 节点。

新增其他 Case 类型时，应新增一个绑定该 `case_type` 的 orchestration Skill，并在其文件夹内提供：

```json
{
  "schema_version": 1,
  "paths": [
    {
      "id": "Containment",
      "title": "隔离处置",
      "description": "形成可审查的隔离范围与处置建议。"
    }
  ]
}
```

Path ID 只要求在同一 orchestration Skill 内唯一。多个同时命中的 orchestration Skill 若对同一 ID 给出不同标题或描述，CapabilityRegistry 会 fail closed。

## 3. 两个 Adapter

### Deterministic

默认启用，不需要 API Key。它稳定把 Skill 声明的全部候选写入 Manifest，并明确标注“未判断当前 Case 的业务优先级”，不再使用静态 `default_rationale` 冒充 Case-specific 判断。前端 Demo 默认只勾选“替代”，但允许 Owner 多选。

```bash
export AGENTIC_CM_ORCHESTRATOR_ADAPTER=deterministic
```

### OpenAI-compatible 模型服务

通用 Adapter 通过官方 `openai-python` 的异步 Chat Completions 客户端调用配置的 `base_url + /chat/completions`，启用兼容性更广的 JSON Object 模式。Pydantic 模型生成响应 Schema 并严格解析结构；平台再校验 Path/option 白名单、角色报告契约与治理边界。平台核心不知道服务商名称；Base URL、API Key、模型 ID、鉴权 Header 和鉴权前缀均由运行时注入。API Key 只用于 SDK 请求 Header，不进入 Case、Manifest、事件或日志。SDK 传输重试关闭，非法结构只进行一次可审计的修复调用；仍失败则本次运行失败且不修改 Case。

```bash
cp .env.example .env
```

在 `.env` 中配置：

```dotenv
AGENTIC_CM_ORCHESTRATOR_ADAPTER=openai-compatible
AGENTIC_CM_PATH_ADAPTER=openai-compatible
AGENTIC_CM_LLM_BASE_URL=https://your-provider.example/v1
AGENTIC_CM_LLM_API_KEY=your-key
AGENTIC_CM_LLM_MODEL=your-model-id
AGENTIC_CM_PATH_MAX_OUTPUT_TOKENS=6000
```

默认使用标准 `Authorization: Bearer <key>`。兼容服务采用其他鉴权格式时可以覆盖：

```bash
export AGENTIC_CM_LLM_API_KEY_HEADER='x-api-key'
export AGENTIC_CM_LLM_API_KEY_PREFIX=''
```

对于不要求鉴权的本地兼容服务，可以不设置 `AGENTIC_CM_LLM_API_KEY`。代码中不包含厂商 Base URL、模型名或 Key 默认值。

## 4. 运行与验收

重置数据后，主 Case 处于 `INTAKE`：

```bash
curl -sS -X POST http://localhost:8000/api/demo/reset \
  -H 'Content-Type: application/json' \
  -d '{"dataset_id":"supply-chain-golden-path-v1"}'

curl -sS -X POST http://localhost:8000/api/cases/CM-2026-014/orchestrate \
  -H 'Content-Type: application/json' \
  -d '{"actor":"陈澄","role":"订单统筹经理"}'
curl -sS 'http://localhost:8000/api/cases/CM-2026-014/manifest?actor=陈澄&role=订单统筹经理' | python3 -m json.tool
curl -sS 'http://localhost:8000/api/cases/CM-2026-014/agent-runs?actor=陈澄&role=订单统筹经理&agent_type=orchestrator' | python3 -m json.tool
curl -sS 'http://localhost:8000/api/cases/CM-2026-014/capabilities?actor=陈澄&role=订单统筹经理'
curl -sS -X POST http://localhost:8000/api/cases/CM-2026-014/manifest/approve \
  -H 'Content-Type: application/json' \
  -d '{"selected_path_ids":["PATH-01"],"actor":"陈澄","role":"订单统筹经理"}'
curl -sS -X POST http://localhost:8000/api/cases/CM-2026-014/paths/PATH-01/execute \
  -H 'Content-Type: application/json' \
  -d '{"actor":"陈澄","role":"订单统筹经理"}'
curl -sS 'http://localhost:8000/api/cases/CM-2026-014/agent-runs?actor=陈澄&role=订单统筹经理&agent_type=path' | python3 -m json.tool
```

Manifest 的具体内容及其能力快照是 Owner-only 数据。非 Owner 的 Case 视图返回 `manifest: null`，直接读取、生成或审批返回 `403`。当前 `actor` / `role` 仅服务于 Demo 身份模拟；生产环境应从可信认证主体映射身份。

### Orchestrator trace 契约

`GET /api/cases/{case_id}/agent-runs` 返回运行级元数据与有序 `events[]`。可用 `agent_type=orchestrator` 过滤。每个事件包含 `sequence`、`step`、`status`、`summary`、`details` 和数据库 UTC 时间。OpenAI-compatible Adapter 的 trace 会保存实际请求 JSON、模型响应正文、HTTP 状态、usage 和结构校验结果，但鉴权 Header 只记录 Header 名与“是否配置”，绝不保存 Key 值。该接口与 Manifest 一样仅 Case Owner 可读。

这里的 trace 是可审计执行轨迹，不是模型隐藏思维链。系统保存提供给模型的事实/候选、模型显式返回的 rationale、平台校验和状态转换；不要求模型输出、也不尝试推断 chain-of-thought。

首版状态：

- `orchestrator` Agent trace：已实现并在 Case 工作台可展开查看，成功和失败运行均保留；
- `path` Agent trace：已实现。Owner 启动已批准 Path 后，平台从该 Path 的冻结 Manifest 快照读取 execution Skill、Policy、Knowledge、编译责任和 Case 快照，组装最小授权 `PathRunContext`；依次审计门禁、Agent 组装、输入、模型请求/响应、结构校验、`SolutionRevision` 组装与持久化。失败运行保留 trace，但不创建业务事件或修改 SolutionRevision；
- `synthesis` Agent trace：待多 Path 结果汇总与冲突检测切片实现后接入；Synthesis 不得引入未探索 Path 或绕过人类批准。

Case Thread 读取 `GET /api/cases/{case_id}/timeline`。该接口从 append-only `domain_events` 投影 Manifest 生成、Owner 批准和各角色 Commitment 批准事件，并返回数据库记录的 UTC 时间；前端按浏览器本地时区显示到秒。投影只包含 Thread 所需字段，不暴露原始事件中的 Manifest Path、Policy 或能力快照。

预期：

- Manifest 包含 `MaterialSubstitution`、`SupplyExpediting`、`OrderSplit`；
- 前端默认只勾选 `MaterialSubstitution`，也允许多选；
- 三条 Path 分别冻结自己的 Policy、execution Skill 与 Knowledge 快照；替代 Path 同时冻结总控 Skill、研发 Skill、主计划 Skill、供应经理 Skill，以及 Skill 自有的 A/B 候选和三种只读模拟查询；
- Owner 批准后 `SUPPLY`、`TECH` 为 `PENDING` 并进入各自角色 Inbox；本人批准后才为 `READY`，`CUSTOMER` 在两者均 `READY` 前保持 `BLOCKED`；
- `PATH-01` 执行时只使用 Manifest 中冻结的 execution Skills、Policy、Knowledge、A/B 候选与 Tool 结果，输出两个选项和研发/主计划/供应经理三个维度的完整句报告，再由平台封装为 `SolutionRevision`；模型不能新增、遗漏候选或角色报告；
- Planner 发明 Path 或返回非法结构时，Case 与事件表均无副作用。
