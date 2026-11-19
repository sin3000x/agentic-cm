# Path Agent Function Tools 与渐进披露设计

## 目标

让 Path Agent 真正通过 Deep Agents 工具循环读取 Manifest 授权的冻结查询数据，而不是由 `PathAgent.run()` 预先生成 `tool_results` 后一次性塞给模型。同时把 Skill、业务上下文和领域校验放回各自边界，保持 API、Manifest、Commitment DAG、`PathAgentResult` 和 `SolutionRevision` 合约不变。

## 权威边界

Capability Registry 和已批准 Manifest 仍是唯一授权来源。Skill 的 `tools.json` 保存只读工具名称、说明、参数键和冻结 records；这些内容进入 Skill digest 和 Manifest 快照。Python Function Tool 只负责在当前快照内按授权候选查询，不硬编码第二份业务数据，也不访问外部系统。

模型不能直接看到整个能力目录。`PathAgent` 只把本次 Manifest 精确解析出的入口 Skill、Bundle 成员、工具和业务上下文交给 Adapter。

## 数据流

```text
CaseService.execute_path
        -> PathAgent.run
           - 校验 Manifest、Policy、Skill、授权候选和工具 records
           - 构造 PathAgentContext（不执行工具）
        -> DeepAgentPathAdapter.generate
           - 投影只读 /skills、/case、/knowledge、/evidence
           - 注册本次授权的 LangChain Function Tools
           - Deep Agents read_file + function-tool loop
           - structured PathAgentResult
        -> PathAgent
           - 中文与 required role reports 领域校验
           - SolutionRevision
```

## 虚拟文件

每次 invocation 只投影当前 Path 所需文件：

- `/skills/<skill-id>/SKILL.md`
- `/skills/<entrypoint-id>/bundle.json`，内容来自 Manifest 冻结的 `skill_selections`
- `/case/snapshot.json`
- `/case/path.json`
- `/case/human-proposal.json`（存在时）
- `/case/previous-solution-revision.json`（存在时）
- `/knowledge/context.json`
- `/evidence/authorized-options.json`
- `/evidence/required-role-reports.json`

user message 只要求读取授权 Skill 和上述上下文后产生 `PathAgentResult`，不再包含 `json.dumps(prompt_payload())`，也不存在 `/evidence/tool-results.json`。

## Function Tools

内置物料替代 Skill 暴露三个工具：

- `lookup_material_master(option_id)`
- `lookup_supply_snapshot(option_id)`
- `lookup_customer_acceptance(option_id)`

工具实现由 Adapter 根据冻结工具契约构造。工具只接受 `authorized_options` 中的 id；未知或未授权 id 返回工具错误，不泄露其他 records。成功调用返回对应冻结 record，并写入产品 trace 的工具名、输入和安全输出。

工具名称、description 和参数结构构成 graph 缓存键。函数从 invocation state 读取当前 Case 的授权范围和 records，因此相同结构的 graph 可以跨 Case 复用而不会串数据。

## Deep Agents 约束

- Skill source 使用显式标签 `Manifest`。
- 主 Agent 只暴露 `ls`、`read_file`、`glob`、`grep` 和本次 Function Tools。
- `FilesystemPermission` 使用 Deep Agents 0.7.11 的 `read` / `write` operation；允许读取 `/skills/**`、`/case/**`、`/knowledge/**`、`/evidence/**`，拒绝其他读取和全部写入。
- 禁用 general-purpose subagent、`task` 和 `execute`。
- 不注册 provider-wide `openai` Harness Profile。确定性模型和生产 Path 模型都通过 Path 专用的 `agentic-cm` provider 标识获得相同约束。
- `DeepAgentPathAdapter` 只负责 graph、工具、schema 和运行错误；中文及角色契约只由 `PathAgent` 校验一次。

## Skill 写法

六份 Skill 的 description 同时表达用途和触发条件。正文描述方法和证据优先级，不引用 user payload 的 JSON 字段。

物料替代入口 Skill 先读自己的 `bundle.json`，再读列出的三个成员 Skill。成员 Skill 调用对应 Function Tool。OrderSplit 和 SupplyExpediting 当前没有专用工具，只能根据已投影 Case、Knowledge 和 HumanProposal 形成待确认建议，不得声称拥有不存在的供应商、库存、物流或客户证据。

## 错误与审计

- 工具定义冲突、缺 record、非法名称或未授权候选在生成或调用边界 fail closed。
- graph 递归耗尽、缺 structured response 或 schema 错误映射为 `AgentOutputError`。
- 模型/工具运行异常映射为 `AgentExecutionError`。
- Adapter 记录 graph 开始、Skill/文件/工具投影、实际 Function Tool 调用、结构化结果或安全失败摘要；不记录凭证和隐藏思维链。
- 任何失败都不能创建或替换 `SolutionRevision`。

## 非目标

- 不连接 ERP、供应商、物流或客户真实系统。
- 不把 Bundle 成员变成 subagent。
- 不增加 `ask_human`、checkpoint、Explore、Memory。
- 不迁移 Orchestrator 或 Synthesis。
- 不改变前端和 HTTP 合约。

## 验收

1. 一个脚本化模型必须先调用真实 Function Tool，再能返回结构化方案。
2. Function Tool 返回 Manifest 冻结 record，并拒绝未授权 option id。
3. 模型首条 user message 不含整包 JSON，所有业务输入均在受限虚拟文件中。
4. 当前 Path 只看到 Manifest 授权的 Skill、Bundle 成员和工具。
5. graph 对相同工具结构复用，对不同工具范围隔离。
6. 中文、角色报告、运行失败和 Case 不变性保持 fail closed。
7. 后端测试、Capability validation、前端 lint/build/test 全部通过。
