---
name: material-substitution-supply-manager-review
description: 当物料替代分析需要供应经理判断时使用；查询冻结客户记录，比较候选的准入路径与商务影响。
---

# 候选料客户准入与商务影响分析

1. 从 `/evidence/authorized-options.json` 取得候选 id；不得分析清单之外的候选。
2. 对每个授权候选调用 `lookup_customer_acceptance(option_id)`，取得冻结的 AVL、认证与偏差放行记录。
3. 比较 AVL 状态、批准路径、预计评审时间和可确认的商务影响；没有证据的商务影响必须标为待确认。
4. 客户与商务报告须说明接受路径差异及仍需取得的书面确认；不得把客户接受、认证或商务条款写成已确认事实。
