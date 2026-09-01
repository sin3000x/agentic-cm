---
name: material-substitution-engineering-review
description: 当物料替代分析需要研发判断时使用；查询冻结物料主数据，比较候选的技术可行性。
---

# 候选料技术可行性分析

1. 从 `/evidence/authorized-options.json` 取得候选 id；不得分析清单之外的候选。
2. 对每个授权候选调用 `lookup_material_master(option_id)`，取得冻结的物料主数据与研发验证记录。
3. 对比封装、引脚兼容性、固件改动和验证状态，区分已知事实、差异与待验证事项。
4. 技术可行性报告须说明推荐理由及仍需研发确认的测试、认证或投产条件；不得把未完成事项写成已确认事实。
