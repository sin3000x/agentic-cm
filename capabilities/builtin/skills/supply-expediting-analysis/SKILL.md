---
name: supply-expediting-analysis
description: 当已批准 SupplyExpediting Path 需要比较供应商、生产或物流加速方案时使用；只基于冻结证据形成可评审的中文建议。
---

# 供应加速分析

1. 读取 `/case/snapshot.json`、`/case/path.json`、`/evidence/authorized-options.json` 和 `/evidence/required-role-reports.json`；如存在，再读取 HumanProposal、上一版方案与 Knowledge 文件。
2. 当前没有为本 Skill 注册外部查询工具。只能使用文件中已有的供应商、生产与物流证据；不得虚构产能、日期、优先级或运输状态。
3. 分别说明有证据支持的供应商产能、最早可行供应日期、生产优先级、运输选项和预计到货日期。缺少证据的日期或数量必须标为待责任角色确认。
4. 输出一份中文推荐方案，并严格按照 `/evidence/required-role-reports.json` 的角色与维度逐项生成报告，说明批准理由与待确认事项。

不得代表采购、供应商、物流或 Case Owner 作出决定，不得作出承诺，也不得修改供应商、生产、物流、ERP、库存或订单系统。
