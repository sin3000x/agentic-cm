# Agent Adapter 契约

Orchestrator 与 Synthesis Agent 使用 `agent_runtime.request_structured_output`：一次网络重试、一次结构修复，然后 fail closed。Path Agent 使用 Deep Agents 图运行时，在原对话中完成一次输出修正，平台仍保留最终校验。错误类型只有：

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

Path Agent 最多进行 12 轮取证；同一工具与参数的冻结业务查询及只读文件操作在一次运行内复用结果（包括查无记录），并行重复调用只执行一次。缓存不跨运行共享。每轮提示已完成的查询，独立文件读取及候选证据查询应并行。累计复用 3 次或取证预算用尽后，移除取证工具，仅保留 `PathAgentResult`，最多两轮提交有效结构化结果。证据不足仍须返回信息请求，不能为了收尾编造方案。

信息请求与方案字段在 `PathAgentResult` 模型校验时互斥，冲突错误列出具体字段（包括 `change_summary`）。角色、中文和修订摘要要求在同一图调用内校验。首次输出错误回传为工具反馈，保留完整消息与证据，并提供旧方案和人工反馈；下一轮关闭全部取证工具，只修正并提交结果。再次输出错误立即失败，不重新运行取证流程。其他 Adapter 仍使用平台的单次修正兜底。

初始消息直接包含 `/case/snapshot.json` 的冻结业务输入，避免读取前猜测编码和日期。物料替代工具只接受 Case 原料编码；成功发现候选后才向模型开放候选证据工具，执行层同样拒绝未发现的编码。供货问题校验使用本 Case 原料的替代候选及明确的料号/日期组合，不采用其他原料的替代记录；错误反馈包含问题索引、提交值和合法组合，供原上下文中的修正使用，平台不自动替换业务值。

图执行上限为 100 步，给工具与中间件节点留出空间，不作为模型轮次预算。取证复用、进入收尾及失败原因均记入 trace；超过预算或输出持续无效时 fail closed，不写入新方案。

`AGENTIC_CM_ADAPTER=deterministic|openai-compatible`。模型、thinking、token 上限按 Agent 前缀覆盖，见 README。Key 只用于请求 Header，不进 Case、事件或 trace。

Deterministic Adapter 用于测试和无 Key 本地开发；它不判断业务优先级。
