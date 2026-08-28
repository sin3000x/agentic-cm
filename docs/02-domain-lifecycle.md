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

`PathAttempt.state`：PLANNED → AWAITING_COMMITMENT → SUCCEEDED / REJECTED，或 REVISING 后重新探索。

`CommitmentNode.status`：BLOCKED / PENDING / READY / STALE / REJECTED。依赖由 Policy `depends_on` 编译，不另存一张 DAG 表。

## 公开时间线

Thread 只投影 `CaseEvent` 中的业务事件。启动期迁移事件已经删除；旧库无法校验时直接重种 demo。
