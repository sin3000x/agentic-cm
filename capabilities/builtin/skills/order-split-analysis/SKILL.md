---
name: order-split-analysis
description: 在 Manifest 批准后分析 OrderSplit Path 的部分交付与分批交付选项，形成可评审的中文方案，不修改订单，也不承诺客户日期。
---

# 订单拆分分析

1. 读取冻结的 Case 快照、HumanProposal、已编译 Policy 和当前可用数量证据。
2. 只能依据有证据支持的数量和日期设计交付批次。
3. 分别说明可立即交付数量、剩余数量、建议批次、客户接受度和剩余承诺。
4. 缺少证据的数量、日期或客户假设必须标记为等待责任角色确认。
5. 按平台 `PathAgentResult/v1` JSON 契约生成可独立评审的中文拆分交付选项，包含 `summary`、`options`、`recommendation` 和 `evidence_gaps`；每个选项须明确可用数量、交付批次、客户接受度和剩余承诺。

不得代表计划、物流、销售、客户或 Case Owner 作出决定，也不得修改 ERP、库存、订单、物流、CRM 或客户系统。
