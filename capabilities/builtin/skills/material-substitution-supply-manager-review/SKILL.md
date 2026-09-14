---
name: material-substitution-supply-manager-review
description: 当物料替代分析需要供应经理判断时使用；查询冻结客户记录，比较候选的准入路径与商务影响。
---

# 候选料客户准入与商务影响分析

1. 从 `/case/snapshot.json` 读取缺料编码与缺口数量，并从 `lookup_material_substitutes` 的结果取得候选的实际 `material_id`；尚未查询时先按 Case 缺料编码查询替代关系。
2. 对每个查得的候选调用 `lookup_customer_acceptance(material_id)`，取得冻结的 AVL、认证与偏差放行记录。
3. 比较 AVL 状态、批准路径、预计评审时间和可确认的商务影响；没有证据的商务影响必须标为待确认。
4. 客户与商务报告须说明接受路径差异及仍需取得的书面确认；不得把客户接受、认证或商务条款写成已确认事实。

查询未返回记录时标为证据缺失，不得把无记录解释为不允许查询，也不得编造替代关系或事实。
客户记录必须与 Case 客户一致；其他客户的 AVL 或认证记录不能证明当前客户接受。
