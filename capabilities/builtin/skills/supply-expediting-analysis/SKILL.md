---
name: supply-expediting-analysis
description: 在 Manifest 批准后分析 SupplyExpediting Path 的供应商、生产与物流加速选项，形成可评审的中文方案，不作供应或交付承诺。
---

# 供应加速分析

1. 读取冻结的 Case 快照、HumanProposal、已编译 Policy，以及当前供应商和物流证据。
2. 分别说明供应商产能、最早可行供应日期、生产优先级、运输选项和预计到货日期。
3. 缺少证据的日期或数量必须在推荐方案或对应角色报告中标明，等待责任角色确认。
4. 输出一份中文推荐方案，并为 `required_role_reports` 中每个契约写一条报告，说明为何该加速方案应在该维度被批准。

不得代表采购、供应商、物流或 Case Owner 作出决定，不得作出承诺，也不得修改供应商、生产、物流、ERP、库存或订单系统。
