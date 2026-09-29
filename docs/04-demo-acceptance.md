# Demo 与验收

## 数据集

`demo_cases()` 种 5 个 Case。完整闭环只跑 `CM-2026-014`（Northstar Mobility MCU-X7 延期）。其余用于列表和身份切换。

身份是客户端自报的 `actor` / `role`，仅用于本地演示。

角色：订单统筹经理（Owner）、主计划、研发、供应经理。

## Golden path

1. Owner 打开 `CM-2026-014`；Orchestrator 生成含提拉 / 替代 / 拆分的 Manifest。
2. Demo UI 默认勾选物料替代；批准后只为所选 Path 建 PathAttempt 和 Commitment。
3. Path Agent 依据冻结 Skill 的 `path-options` 写出中文推荐方案和角色报告。
4. 主计划与研发并行审批，供应经理依赖二者。
5. 全部 READY 后进入 FINAL_REVIEW；Synthesis 汇总；Owner CLOSE / KEEP_OPEN / MODIFY。

REVISE 必须填写理由并携带被审版本，回到 PATH_EXPLORATION；新版方案说明改动，同 Path 全部重新审批。REJECT 同样必须填写理由并携带版本，结束该 Path；理由进入汇总依据。

## 信息补充与修订验收

1. Path 缺少必需事实时，Agent 提出问题；Path 为 AWAITING_INFORMATION，不新增方案版本。
2. 指定角色在「我的待办」或 Case 中回答。其他角色、空回答和重复回答被拒绝；等待期间不能再次执行 Path。
3. 全部回答完成后，Owner 继续推演。Agent 收到带来源的回答；原始业务事实不被静默覆盖，答案不等于审批。
4. 先由主计划批准 v1，再由研发填写理由要求修改；Agent 收到理由并生成 v2，主计划也需要重审。
5. 旧页面提交 v1 审批被拒绝。时间线保留问题、回答、理由、版本及改动说明。

Deterministic 模式在 Case 缺少缺料数量或需要到料日期时提出信息请求，可用隔离测试数据验证这个闭环；默认完整 Demo 数据保持原黄金路径。

## 必须保持的边界

- 非 Owner 读 Case 时 `manifest` 和 `synthesis_report` 为 null。
- Manifest 引用 digest 失配则 fail closed，不改 Case。
- Planner / Path 输出必须是 Catalog / 冻结授权的子集。
- Agent 失败只留 trace。
