---
name: material-substitution-master-planning-review
description: 当物料替代分析需要主计划判断时使用；查询冻结供应快照，比较候选的缺口覆盖与交付可行性。
---

# 候选料供应覆盖与交期分析

1. 从 `/case/snapshot.json` 读取缺料编码与缺口数量，并从 `lookup_material_substitutes` 的结果取得候选的实际 `material_id`；尚未查询时先按 Case 缺料编码查询替代关系。
2. 对每个查得的候选调用 `lookup_supply_snapshot(material_id)`，取得冻结的库存、调拨与补货记录。
3. 计算并比较现货覆盖、剩余缺口、调拨周期、补量需求和补量周期；缺少必要输入时明确标为待确认，不得自行补值。
4. 供应与交付报告须指出数量与周期差异，以及仍需主计划确认的库存和日期。冻结快照不代表锁定库存、排产或交付承诺。

查询未返回记录时标为证据缺失，不得把无记录解释为不允许查询，也不得编造替代关系或事实。
