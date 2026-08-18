# Demo 剧情与 MVP 验收标准

## 1. Demo 数据集

固定准备 4–5 个 Case，用于展示 Case Graph；只完整运行订单延期主 Case。

建议数据：

1. `订单预计延期`：主演示 Case；
2. `供应商交付异常`：与主 Case 存在 blocked-by 或 related-to 关系；
3. `替代料认证缺口`：主 Case 的派生 Case；
4. 一个无关订单异常；
5. 一个已关闭历史 Case，用于提供 Experience。

固定角色与 Actor：

- 订单履行经理：Case Owner；
- 主计划；
- 研发；
- 一线经理；
- 大调度：Coordinator。

Role Switcher 用于模拟不同 Actor 操作，页面必须持续显示 `Demo identity simulation`。

## 2. 主 Golden Path

### 2.1 Case 与 Manifest

1. 从 Case Graph 打开订单延期 Case；
2. 查看 Case 结构化信息和 HumanProposal；
3. HumanProposal 建议探索物料替代；
4. Orchestrator 结合 Capability、Policy 和 Experience 生成 Manifest；
5. Manifest 只包含一个准备执行的 Path：`MaterialSubstitution`；
6. Owner 可以删除该 Path或批准它；
7. 批准后创建对应 PathAttempt 和 CommitmentDAG。

### 2.2 方案生成与并行评审

Path Agent 生成两个已经过初步推演的候选：

- A：首选替代料；
- B：备选替代料。

`supply` 和 `technical` Section 都同时覆盖 A 与 B。

CommitmentDAG 中：

- 主计划确认 A/B 的供应可行性；
- 研发确认 A/B 的技术可行性；
- 两个节点没有互相依赖，因此并行开放；
- 一线经理节点等待两项上游承诺完成。

### 2.3 客户反馈与局部重审

一线经理确认：

- A 因客户所在地区的气候、法规或政治约束不可接受；
- B 可以继续沟通并被客户接受。

一线经理提交 `REQUEST_CHANGES`。Path Agent 生成新 SolutionRevision，将最终推荐从 A 调整为 B。

系统比较 Section：

- `supply` 未变化，仍覆盖 B；
- `technical` 未变化，仍覆盖 B；
- `customer` 变化；
- `overall_recommendation` 变化。

因此主计划与研发 Commitment 保持有效，仅一线经理重新评审并 `COMMIT`。

如果新版本引入未被上游承诺覆盖的物料 C，则必须让主计划与研发重新审批；demo 不得为了展示优化而错误保留旧承诺。

### 2.4 汇总与关闭

1. PathAttempt 进入 `DONE + SUCCEEDED`；
2. 所有批准 Path 均已终态；
3. Synthesis Agent 检查结果并生成单 Path 决策简报；
4. Case Owner 点击 `CLOSE`；
5. 平台自动保存当前 CaseSynthesis、PathResult、SolutionRevision 与有效 Commitments 快照；
6. Case 进入 `CLOSED`，不触发外部业务系统操作；
7. 平台生成一条待审核 MemoryCandidate。

## 3. 失败 Preset

第二个可重置 preset 不作为主演示，但用于验证失败闭环：

1. Path Agent 生成替代方案；
2. 研发提交 `DECLINE`；
3. 当前 PathAttempt 进入 `DONE + FAILED`；
4. Synthesis Agent 说明当前没有已验证可行方案；
5. Owner 选择 `PENDING`；
6. 平台自动保存决定快照。

## 4. 核心页面

首版只做：

1. `Case Graph/List`
2. `Case Workspace`
3. `Manifest Review`
4. `Path + CommitmentDAG`
5. `Final Synthesis`
6. 共用 `Role Inbox`

Capability、Policy、Experience 和调用记录使用只读抽屉或详情页。首版不做资产管理后台和通用 DAG 编辑器。

## 5. 演示指标

页面自动显示：

- `parallel review branches`
- `preserved commitments`
- `re-review avoided`

指标根据真实 DAG 和修订事件计算。不得声称节省了真实业务时间，也不得用虚构基线宣称减少了真实审批人数。

Golden Path 的预期解释是：

- 主计划与研发并行，而非串行等待；
- Agent 提前准备 A/B 候选集合；
- A 被客户拒绝后，B 已在上游承诺范围内；
- 平台只让受影响的一线经理重新评审。

## 6. 功能验收清单

### 6.1 Case 与 Manifest

- [ ] Case Graph 能展示固定 Case 及其关系；
- [ ] Case 包含标题、描述、Owner、状态和可为空的 HumanProposal；
- [ ] HumanProposal 修改产生新版本；
- [ ] Orchestrator 能生成版本化 Manifest；
- [ ] Owner 可以在批准前删除 Path；
- [ ] Owner 批准的是保留的全部 Path；
- [ ] 已批准 Manifest 不可原地修改；
- [ ] 批准后的 Path 删除或取消保留审计历史。

### 6.2 Policy 与资产

- [ ] 强制 Policy 通过结构化条件匹配；
- [ ] Agent 不能删除强制 Policy 要求；
- [ ] Manifest 记录 CapabilityBundle、Policy、Experience 的 ID 和版本；
- [ ] Experience 明确标记为历史建议，而非当前事实；
- [ ] Case 完成后只生成待审核 MemoryCandidate。

### 6.3 CommitmentDAG

- [ ] DAG 能正确计算 ready 节点；
- [ ] 主计划与研发节点能够并行开放；
- [ ] 下游节点在前置条件满足前不可提交；
- [ ] 具体 Actor 通过角色 Inbox 认领并签署；
- [ ] Coordinator 不能代替其他业务角色 COMMIT；
- [ ] COMMIT、REQUEST_CHANGES、DECLINE 均保留 Actor、角色、版本和时间；
- [ ] DECLINE 使当前 PathAttempt 进入 FAILED；
- [ ] 技术运行失败不会被记录为业务 DECLINE。

### 6.4 方案修订与局部重审

- [ ] SolutionRevision 不可变；
- [ ] 新版本保存 Section diff；
- [ ] 变化 Section 对应节点变为 STALE；
- [ ] 相关下游节点变为 STALE；
- [ ] 无关 Commitment 保持有效；
- [ ] 引入候选 C 时能正确触发供应和技术重审；
- [ ] 修订轮数上限来自 Manifest 中冻结的配置；
- [ ] 达到修订上限时保持 AWAITING_HUMAN，并产生 revision_limit_reached blocker；
- [ ] Owner 可以留痕追加一轮。

### 6.5 Agent Adapter

- [ ] 平台核心不依赖具体 Agent 框架；
- [ ] Deterministic Adapter 可以完成完整 Golden Path；
- [ ] 一个模型 Adapter 通过相同 contract tests；
- [ ] Adapter 只能获得冻结的 PathRunContext 与授权 Tool；
- [ ] Agent 非法输出不会创建 SolutionRevision 或改变业务状态；
- [ ] Tool 调用具有完整审计记录；
- [ ] 审计中不保存 API Key 或隐藏 chain-of-thought。

### 6.6 汇总与 Owner 决定

- [ ] 所有当前批准 Path 达到终态前不能生成 CaseSynthesis；
- [ ] 后端模型支持至少两个 PathAttempt 并行；
- [ ] Synthesis 只引用已有 PathResult 和 Commitment；
- [ ] CaseSynthesis 版本化，OwnerDecision 引用具体版本；
- [ ] Owner 可以选择 CLOSE 或 PENDING；
- [ ] 平台自动保存决定时的完整快照；
- [ ] CLOSE 不触发真实业务系统修改。

## 7. 自动化验证要求

最低自动化测试覆盖：

- Manifest 版本不可变；
- Policy 强制约束；
- CommitmentDAG ready 计算；
- 并行节点开放；
- Section 变化和局部失效；
- 无关 Commitment 保留；
- DECLINE 到 FAILED；
- 可配置修订轮数与人工追加；
- 非法 Agent 输出无业务副作用；
- 多 Path 汇总门槛；
- OwnerDecision 自动快照；
- 两个 Adapter 的统一 contract tests；
- 一条前端 Golden Path 自动化测试。

视觉布局、图形可读性、Role Switcher 状态和页面中的 demo 安全提示需要人工检查。

## 8. Demo Reset

系统提供只针对固定 demo 数据集的 Reset 操作：

- 恢复固定 Case 和关系；
- 恢复组织、角色与 Actor；
- 恢复已发布 Capability、Policy 和 Experience；
- 清除本轮生成的 Manifest、PathAttempt、审批、AgentRun 和事件；
- 恢复 Golden Path 或失败 preset 的初始状态。

Reset 必须验证目标数据集 ID，不得实现为无边界的通用清库按钮。

## 9. MVP 完成定义

以下条件全部满足才算 MVP 完成：

1. Golden Path 可以从 Case Graph 连续运行到 Case CLOSED；
2. 所有关键状态和审批来自真实用户操作或 Agent Adapter 输出，而非前端动画伪造；
3. 并行审批与局部重审有事件和指标证据；
4. Deterministic Adapter 稳定复现全流程；
5. 模型 Adapter 证明契约可插拔；
6. 后端测试证明多 Path 汇总门槛有效；
7. 失败 preset 可以到达 FAILED 与 PENDING；
8. 全链路 Artifact、版本、Actor、角色和时间可审计；
9. 页面明确说明不接真实业务系统、无生产级身份权限；
10. 本设计文档与实现没有未记录的语义偏离。
