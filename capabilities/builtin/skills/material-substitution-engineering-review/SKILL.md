---
name: material-substitution-engineering-review
description: 从研发视角评审 MaterialSubstitution 冻结候选 A、B，输出一条完整的中文技术可行性报告，但不代表研发批准。
---

# 研发替代评审

1. 只评审 Manifest 冻结的 A（MCU-X7A）与 B（MCU-X7B），不得新增候选料。
2. 使用 `mock.material-master.lookup` 的封装、引脚、固件改动和验证状态，分别说明 A/B 的技术可行性。
3. A 无需固件改动，但 EMC 差异测试尚未确认；B 需要寄存器配置和约 3 个工作日回归测试，整机回归尚未确认。
4. 输出一条以“研发维度：”开头的完整中文句子，必须同时提到 A、B、已知差异和仍需研发确认的事项。
5. 该报告是 Agent 提案材料，不代表研发已经批准 TECH Commitment。

不得声称测试已经执行、认证已经通过或替代料已经投产。
