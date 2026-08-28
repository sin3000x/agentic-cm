# Demo 与验收

## 数据集

`demo_cases()` 种 5 个 Case。完整闭环只跑 `CM-2026-014`（Northstar Mobility MCU-X7 延期）。其余用于列表和身份切换。

身份是客户端自报的 `actor` / `role`，仅用于本地演示。

角色：订单统筹经理（Owner）、主计划、研发、供应经理。

## Golden path

1. Owner 打开 `CM-2026-014`；Orchestrator 生成含提拉 / 替代 / 拆分的 Manifest。
2. Demo UI 默认勾选物料替代；批准后只为所选 Path 建 PathAttempt 和 Commitment。
3. Path Agent 按冻结 Skill 的 `path-options.json` 提出候选 A/B。
4. 主计划与研发并行审批，供应经理依赖二者。
5. 全部 READY 后进入 FINAL_REVIEW；Synthesis 汇总；Owner CLOSE / KEEP_OPEN / MODIFY。

REVISE 把节点标 STALE 并回到 PATH_EXPLORATION。REJECT 结束该 Path。

## 必须保持的边界

- 非 Owner 读 Case 时 `manifest` 和 `synthesis_report` 为 null。
- Manifest 引用 digest 失配则 fail closed，不改 Case。
- Planner / Path 输出必须是 Catalog / 冻结授权的子集。
- Agent 失败只留 trace。
