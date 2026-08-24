---
name: supply-expediting-analysis
description: 在 Manifest 批准后分析 SupplyExpediting Path 的供应商、生产与物流加速选项，形成可评审的中文方案，不作供应或交付承诺。
---

# 供应加速分析

1. 读取冻结的 Case 快照、HumanProposal、已编译 Policy，以及当前供应商和物流证据。
2. 分别说明供应商产能、最早可行供应日期、生产优先级、运输选项和预计到货日期。
3. 缺少证据的日期或数量必须标记为等待责任角色确认。
4. 按平台 `PathAgentResult/v1` JSON 契约生成可独立评审的中文加速选项，包含 `summary`、`options`、`recommendation` 和 `evidence_gaps`；供应商产能、加速日期、运输选项和到货日期在确认前必须列入假设或证据缺口。

不得代表采购、供应商、物流或 Case Owner 作出决定，不得作出承诺，也不得修改供应商、生产、物流、ERP、库存或订单系统。
