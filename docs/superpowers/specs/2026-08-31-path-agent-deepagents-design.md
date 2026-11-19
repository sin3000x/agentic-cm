# Path Agent 迁移至 Deep Agents 设计

## 目标

把当前 Path Agent 的一次性 OpenAI-compatible 结构化请求替换为受约束的 Deep Agents 运行图，同时保持现有 Demo 的业务行为、HTTP API、Manifest、Policy、Commitment DAG 和 `SolutionRevision` 合约不变。

这个切片只证明 Deep Agents 可以安全承载现有 Path Agent。它不实现 Explore Case、不引入 `ask_human` Inbox Task、不新增多轮暂停恢复，也不改变 Orchestrator 或 Synthesis Agent。

## 当前边界

`CaseService.execute_path()` 仍负责 AgentRun、并发冲突检查和结果持久化。`PathAgent` 仍负责从已批准 Manifest 解析冻结的 Skill、Policy、Knowledge、授权候选和只读 Tool 结果，并在写入 `SolutionRevision` 前执行中文、候选白名单、推荐项和角色报告校验。

被替换的部分仅是 `PathAgentAdapter.generate(context, trace)` 的模型执行方式：

- 现状：手工构造 Chat Completions 请求，一次调用返回 `PathAgentResult`，失败时进行一次结构化修复。
- 目标：使用一个受约束的 Deep Agents graph 读取已授权 Skill，运行标准 Agent/tool loop，并以 `PathAgentResult` 作为 structured response。

## 架构

保留现有 `PathAgentAdapter` 协议，增加 `DeepAgentPathAdapter` 作为唯一的 Path 模型运行实现。`PathAgent` 继续是领域装配与验证边界，Deep Agents 只负责模型循环、Skill 渐进披露、上下文状态和结构化输出。

```text
CaseService.execute_path
        ↓
PathAgent.run
        ├── Manifest / CapabilityRegistry 解析
        ├── 只读模拟 Tool 查询
        └── PathAgentContext
                ↓
        DeepAgentPathAdapter.generate
                ├── 受控虚拟 /skills
                ├── Deep Agents graph
                ├── structured PathAgentResult
                └── runtime trace bridge
        ↓
PathAgent 业务契约校验
        ↓
SolutionRevision + Commitment 流程
```

Path Agent 和后续 Explore Agent 将共享这个 Deep Agents graph 装配方式；差异只允许存在于 Capability Scope。当前切片不创建 Explore 专用类或 Runtime。

## Deep Agents 配置

依赖约束为 `deepagents>=0.7.11,<0.8` 和兼容的 `langchain-openai` 1.x。Deep Agents 0.7.11 要求 Python 3.11 以上，符合当前项目要求。

每次 `generate()` 构造或复用一个配置一致的 graph：

- 模型使用 `ChatOpenAI`，读取现有 Path 专属模型、Base URL、API key、超时、thinking 和 reasoning effort 配置。
- `response_format` 固定为 `PathAgentResult`。
- 不配置 Memory。
- 禁用默认 general-purpose subagent，不暴露 `task`。
- 不允许 `write_file`、`edit_file` 或 `execute`。
- 只允许读取本次 Path 投影到虚拟 `/skills/` 下的文件。
- 当前切片不配置 `ask_human` interrupt。
- 使用有限最大模型轮次；达到限制时转换为 `AgentOutputError`，不修改 Case。

Deep Agents 的文件系统只承载本次运行的 Skill 上下文，不承载 Case、Manifest、Policy、SolutionRevision 或业务事件。平台数据库继续是唯一业务事实源。

## Skill 投影

`CapabilityRegistry` 继续是 Skill 的唯一权威来源。不得让 Deep Agents 直接扫描 `capabilities/builtin/skills`，否则会绕过 local override、Bundle 展开、Manifest version/digest 校验和本次授权范围。

`PathAgentContext.execution_skills` 已包含 Manifest 精确解析后的 Skill payload。Adapter 为每个 payload 生成一个只读虚拟文件：

```text
/skills/<skill-id>/SKILL.md
```

文件由已解析 payload 中的 `id`、`description` 和 `instructions_markdown` 构造。入口 Skill 和 Bundle 成员分别投影，Deep Agents Skills Middleware 先暴露 metadata，再按需读取完整指令。

当前 Path 的 `authorized_options`、Knowledge、只读 Tool 结果、Human Proposal、必需角色报告和上一版 SolutionRevision 仍通过最小业务上下文传入，不写入 Skill 文件。当前切片继续复用现有 Python 只读 Tool 查询；把 `tools.json` 变成 Deep Agents Function Tools 留给后续独立切片。

## 模型与确定性测试

生产模式使用 `ChatOpenAI` 指向现有 OpenAI-compatible endpoint。环境变量名称和优先级不变，`path_agent_from_environment()` 返回 `DeepAgentPathAdapter`。

确定性模式也必须经过同一 Deep Agents graph。它通过注入一个脚本化 LangChain chat model 生成既定 structured response，而不是保留一套绕过 graph 的确定性 Path Agent 逻辑。现有 `AGENTIC_CM_DETERMINISTIC_DELAY_SECONDS` 在脚本化模型调用中生效。

测试可直接注入脚本化模型或 Deep Agents graph factory，避免访问外部模型。测试不得依赖 Ambient `.env`。

## 输出验证和错误处理

Deep Agents 的 structured response 负责 Pydantic schema 验证；`PathAgent` 继续负责业务语义验证：

- 结果必须包含中文内容；
- 只能返回全部授权候选，不能发明或遗漏候选；
- 推荐项必须属于结果候选；
- 角色报告必须与冻结 Policy 要求一致；
- 失败不能创建或替换 `SolutionRevision`。

模型连接、超时和上游服务错误映射为 `AgentExecutionError`。模型达到最大轮次、没有 structured response 或 schema 无法收敛映射为 `AgentOutputError`。Capability version/digest 失效仍在进入 Deep Agents 前失败。

现有一次手工 JSON 修复循环不再保留；由 Deep Agents/LangChain structured output 和有限 Agent turns 负责收敛。业务语义校验仍 fail closed，不自动放宽。

## Trace 与审计

现有 `agent_runs` 和 `agent_trace_events` 继续是产品审计入口，不依赖 LangSmith。

Adapter 至少记录：

- `deepagent.runtime.started`：模型 profile、Path、Skill id、最大轮次；
- `deepagent.skill.projected`：本次允许的 Skill refs，不记录未授权 Skill；
- `deepagent.model.completed`：轮次、token usage 和结构化输出摘要；
- `deepagent.runtime.failed`：错误类型和安全错误摘要；
- 现有 `solution_revision.compose` 仍由 `PathAgent` 记录。

不得记录 API key、认证值或隐藏思维链。模型消息和 Tool 事件只保留可审计的输入、输出和调用摘要。

## API 与前端

本切片不修改 API 路径、请求体、Case 序列化或前端交互。`POST /api/cases/{case_id}/paths/{path_id}/execute` 仍返回相同 Case 结构，前端仍显示相同 SolutionRevision、责任节点和 Path Trace。

由于当前切片没有 `ask_human`，Path Attempt 不新增 `WAITING_HUMAN` 状态，Inbox 也不新增信息任务。

## 测试范围

至少覆盖：

1. 受控 Skill 投影只包含 Manifest 已授权的入口和成员，且保持标准 `SKILL.md` frontmatter。
2. Deep Agents graph 返回的 structured response 被转换为现有 `PathAgentResult`。
3. 确定性模式与 OpenAI-compatible 模式都装配相同 graph，只替换模型实现。
4. 模型发明候选、遗漏角色报告或返回非中文内容时，Case 与 SolutionRevision 不变。
5. Deep Agents 运行失败时 AgentRun 保留失败 Trace，业务状态不变。
6. Path 模型、Base URL、超时和 thinking 配置继续遵循现有环境变量。
7. 后端完整 pytest、capability validation、前端 lint/build/test 通过。

## 非目标

- Explore Case Type 和无 Manifest 执行。
- `ask_human` Tool、InformationRequest 和 Inbox 回答。
- 多轮 checkpoint 的数据库恢复。
- Deep Agents 长期 Memory、子 Agent、Shell 或可写文件系统。
- 将 `tools.json` 动态注册为 Function Tools。
- 迁移 Orchestrator 或 Synthesis Agent。

这些能力必须在当前替换稳定、测试证明业务边界未回归后，作为独立切片设计。
