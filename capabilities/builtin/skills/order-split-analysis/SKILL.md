---
name: order-split-analysis
description: 当已批准 OrderSplit Path 需要设计部分交付或分批交付方案时使用；只基于冻结证据形成可评审的中文建议。
---

# 订单拆分分析

1. 读取 `/case/snapshot.json`、`/case/path.json`、`/evidence/authorized-options.json` 和 `/evidence/required-role-reports.json`；如存在，再读取 HumanProposal、上一版方案与 Knowledge 文件。
2. 当前没有为本 Skill 注册外部查询工具。只能依据文件中已有证据设计交付批次；不得虚构库存、日期、客户反馈或系统状态。
3. 分别说明可立即交付数量、剩余数量、建议批次、客户接受度和剩余承诺。缺少证据的数量、日期或客户假设必须标为待责任角色确认。
4. 输出一份中文推荐方案，并严格按照 `/evidence/required-role-reports.json` 的角色与维度逐项生成报告，说明批准理由与待确认事项。

不得代表计划、物流、销售、客户或 Case Owner 作出决定，也不得修改 ERP、库存、订单、物流、CRM 或客户系统。
