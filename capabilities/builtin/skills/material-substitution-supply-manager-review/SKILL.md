---
name: material-substitution-supply-manager-review
description: 分析 MaterialSubstitution 冻结候选 A、B 的客户 AVL、偏差放行、正式认证与商务影响，输出中文客户准入报告，但不代表客户作出决定。
---

# 候选料客户准入与商务影响分析

1. 只分析 Manifest 冻结的 A（MCU-X7A）与 B（MCU-X7B），不得新增候选料。
2. 使用 `mock.customer-acceptance.lookup` 比较客户 AVL、偏差放行、正式认证和预计评审路径。
3. A 属于同系列但具体料号仍需客户书面偏差放行；B 不在当前 AVL，需要正式替代认证和商务影响确认。
4. 输出一条以“供应经理维度：”开头的完整中文句子，必须同时提到 A、B、客户接受路径差异和仍需供应经理取得的书面确认。
5. 该报告是 Agent 提案材料，不代表客户接受、商务条款确认或 CUSTOMER Commitment 已经完成。

不得代表客户、销售或 Case Owner 作出接受与交期承诺。
