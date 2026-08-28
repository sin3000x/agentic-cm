---
name: material-substitution-master-planning-review
description: 分析 MaterialSubstitution 冻结候选 A、B 对缺口的数量覆盖、调拨周期与补量需求，输出中文供应与交付可行性报告，但不承诺库存或日期。
---

# 候选料供应覆盖与交期分析

1. 只分析 Manifest 冻结的 A（MCU-X7A）与 B（MCU-X7B），不得新增候选料。
2. 使用 `mock.supply-snapshot.lookup` 对照 Case 的 18,400 pcs 缺口，分别判断 A/B 的数量覆盖、调拨周期和补量需求。
3. A 的模拟现货为 12,000 pcs，剩余 6,400 pcs 模拟补货周期为 5 天；B 的模拟现货为 18,400 pcs，模拟调拨周期为 3 天。
4. 输出一条以“主计划维度：”开头的完整中文句子，必须同时提到 A、B、数量覆盖差异和仍需主计划确认的库存/交期事项。
5. 该报告是 Agent 提案材料，不代表主计划已经锁定库存、排产或批准 SUPPLY Commitment。

不得把模拟库存、调拨天数或补货周期表述为已承诺事实。
