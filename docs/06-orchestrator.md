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

通用 Adapter 调用配置的 `base_url + /chat/completions`，启用 JSON Output。平台核心不知道服务商名称；Base URL、API Key、模型 ID、鉴权 Header 和鉴权前缀均由运行时注入。API Key 只用于请求 Header，不进入 Case、Manifest、事件或日志。非法 JSON/Schema 会进行一次修复调用；仍失败则本次编排失败且 Case 保持 `INTAKE`。

```bash
cp .env.example .env
```

在 `.env` 中配置：

```dotenv
AGENTIC_CM_ORCHESTRATOR_ADAPTER=openai-compatible
AGENTIC_CM_LLM_BASE_URL=https://your-provider.example/v1
AGENTIC_CM_LLM_API_KEY=your-key
AGENTIC_CM_LLM_MODEL=your-model-id
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

curl -sS -X POST http://localhost:8000/api/cases/CM-2026-014/orchestrate
curl -sS http://localhost:8000/api/cases/CM-2026-014/manifest | python3 -m json.tool
curl -sS http://localhost:8000/api/cases/CM-2026-014/capabilities
curl -sS -X POST http://localhost:8000/api/cases/CM-2026-014/manifest/approve \
  -H 'Content-Type: application/json' \
  -d '{"selected_path_ids":["PATH-01"]}'
```

预期：

- Manifest 包含 `MaterialSubstitution`、`SupplyExpediting`、`OrderSplit`；
- 前端默认只勾选 `MaterialSubstitution`，也允许多选；
- 三条 Path 分别冻结自己的 Policy、execution Skill 与 Knowledge 快照；提拉、替代、拆分分别命中 `supply-expediting-analysis`、`material-substitution-analysis`、`order-split-analysis`；
- Owner 批准后 `SUPPLY`、`TECH` 为 `PENDING` 并进入各自角色 Inbox；本人批准后才为 `READY`，`CUSTOMER` 在两者均 `READY` 前保持 `BLOCKED`；
- Planner 发明 Path 或返回非法结构时，Case 与事件表均无副作用。
