# 领域模型与状态机

权威类型在 `backend/agentic_cm/domain.py`。下面只记录运行中的形状，不是规划中的扩展。

## Case

`Case` 是业务事实源。字段：`id`、`title`、`description`、`status`（OPEN/CLOSED）、`phase`、`owner`、`owner_role`、`business_payload`、`human_proposal`、`classification`、`manifest`、`path_attempts`、`commitment_nodes`、`synthesis_report`、`owner_decision`、`version`、时间戳。

没有独立的 Case Graph 表。Demo 数据集里的其他 Case 只是列表里的邻居。

## 阶段

```
INTAKE
  → Orchestrator 生成 Manifest
MANIFEST_REVIEW
  → Owner 勾选 Path 并批准
PATH_EXPLORATION
  → Path Agent 为每条已选 Path 写入 SolutionRevision
PROFESSIONAL_COMMITMENT
  → 角色在 Inbox 中 APPROVE / REVISE / REJECT
FINAL_REVIEW
  → Synthesis 汇总；Owner CLOSE / KEEP_OPEN / MODIFY
```

`MODIFY` 清空 Manifest 与 Path 状态，把指导写入新的 HumanProposal，回到 INTAKE。

## Manifest

`ManifestPath` 保存：

- `definition` + `rationale`
- `skill_selections`（入口、中文理由、Bundle 成员）
- `policies` / `knowledge` 的 `AssetRef`

YAML 下载就是这份模型。展示用中文标题只加在 Case view 上，不写进冻结 YAML。

## PathAttempt 与 Commitment

`PathAttempt.state`：PLANNED → AWAITING_COMMITMENT → SUCCEEDED / REJECTED，或 REVISING 后重新探索。缺少必要事实时进入 AWAITING_INFORMATION，Case 保持 PATH_EXPLORATION，不产生新方案版本。

`CommitmentNode.status`：BLOCKED / PENDING / READY / STALE / REJECTED。依赖由 Policy `depends_on` 编译，不另存一张 DAG 表。

专业审批必须提交用户实际查看的 `expected_revision`；REVISE / REJECT 必须带非空 `reason`。事件保留被审版本、理由和方案/角色报告快照。修订意见进入下一轮 Path 上下文；新方案用 `change_summary` 说明变化，同 Path 的全部节点重新评审，旧 READY 不覆盖新版。

同一 Case / Path 的方案版本跨 Manifest 轮次递增，Owner MODIFY 后旧页面也不能批准新一轮方案。

## 人工补充信息

Path Agent 可以返回 `information_requests`，写明责任角色、具体问题和缺失原因。平台校验角色属于该 Path 冻结 Policy，再分配请求 ID，保存到 `PathAttempt.information_requests`。信息请求与完整方案互斥。

Inbox 分别显示专业审批与补充信息。指定角色通过独立回答接口提交文本，平台保留回答者和时间；答案不会覆盖原始业务数据或自动形成承诺。所有问题答齐后，Path 回到 PLANNED 或 REVISING，由 Owner 继续推演。已回答资料保留为后续 Agent 的带来源上下文，后续仍可提出新的具体问题。

时间线完整展示提问、回答、修改理由、新方案版本和改动说明。

## 公开时间线

Thread 只投影 `CaseEvent` 中的业务事件。启动期迁移事件已经删除；旧库无法校验时直接重种 demo。
