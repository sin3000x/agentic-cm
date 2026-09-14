---
name: material-substitution-engineering-review
description: 当物料替代分析需要研发判断时使用；查询冻结物料主数据，比较候选的技术可行性。
---

# 候选料技术可行性分析

1. 从 `/case/snapshot.json` 读取缺料编码与缺口数量，并从 `lookup_material_substitutes` 的结果取得候选的实际 `material_id`；尚未查询时先按 Case 缺料编码查询替代关系。
2. 对每个查得的候选调用 `lookup_material_master(material_id)`，取得冻结的物料主数据与研发验证记录。
3. 对比封装、引脚兼容性、固件改动和验证状态，区分已知事实、差异与待验证事项。
4. 技术可行性报告须说明推荐理由及仍需研发确认的测试、认证或投产条件；不得把未完成事项写成已确认事实。

查询未返回记录时标为证据缺失，不得把无记录解释为不允许查询，也不得编造替代关系或事实。
