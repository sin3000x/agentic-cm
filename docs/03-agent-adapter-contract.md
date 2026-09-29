# Agent Adapter 契约

三个 Agent 共用 `agent_runtime.request_structured_output`：一次网络重试、一次结构修复，然后 fail closed。错误类型只有：

- `AgentError` → HTTP 409
- `AgentOutputError` → HTTP 409（可修复的非法输出）
- `AgentExecutionError` → HTTP 502

## 职责

| Agent | 输入 | 输出 | 不能做 |
|---|---|---|---|
| Orchestrator / Planner | Case 摘要、Catalog Path、可见 Skill 入口 | 每条 Path 的 rationale + Skill 选择 | 发明/省略 Path，选择 Bundle 成员，改 Policy |
| Path Agent | 已批准 Manifest 冻结引用、只读 tool 结果、专业修改意见、人工补充资料 | 完整 `PathAgentResult` 或信息请求 | 编造缺失事实，改 Case，把资料补充当作审批 |
| Synthesis Agent | 全部终态 PathAttempt + Commitment | `SynthesisResult` | 补造未探索 Path，杜撰 supporting_refs |

平台在 Adapter 之外校验白名单，然后把 LLM 输出加上 `revision` / `generated_by` 写成 `SolutionRevision` 或 `SynthesisReport`。不要再复制一套 dataclass。

Path 输出有两种互斥结果：完整方案包含 `recommendation` 和所有必需的 `role_reports`；缺信息时只返回 `information_requests`（`role/question/reason`），不生成 `SolutionRevision`。平台只接受冻结 Policy 中已有的责任角色，最多十个不重复问题。修订后的完整方案必须提供 `change_summary`。

`/case/review-feedback.json` 提供当前方案版本收到的修改理由；`/case/human-information.json` 提供已回答的问题、资料和来源。它们是业务输入，不改变 Agent 的工具权限或强制审批义务。

## 运行时

`AGENTIC_CM_ADAPTER=deterministic|openai-compatible`。模型、thinking、token 上限按 Agent 前缀覆盖，见 README。Key 只用于请求 Header，不进 Case、事件或 trace。

Deterministic Adapter 用于测试和无 Key 本地开发；它不判断业务优先级。
