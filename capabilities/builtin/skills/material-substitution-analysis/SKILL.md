---
name: material-substitution-analysis
description: 分析已批准物料替代 Path 中的候选料，形成覆盖供应、技术、客户接受度与总体建议的结构化中文方案，不作业务承诺，也不修改业务系统。
---

# 物料替代分析

1. 读取 Manifest 冻结的 Case 快照、HumanProposal、已编译 Policy 和所引用的 Knowledge。
2. 候选集只能来自本 Skill 包冻结的 `path-options.json`：A 为 MCU-X7A，B 为 MCU-X7B。不得从框架默认值读取候选；如需新增候选，必须先请求修订 Path。
3. 对 A、B 分别使用 `tools.json` 中全部冻结的只读查询。返回记录属于模拟证据快照，不得表述为实时 ERP、库存、研发或客户事实。
4. 同时应用 Manifest 中的三个角色 Skill：研发替代评审、主计划替代评审和供应经理替代评审。
5. 为 A、B 各生成一个可独立评审的选项，比较技术可行性、供应与交付可行性、客户与商务接受度、收益、风险及假设，不得把未知信息写成事实。
6. 缺少当前证据的结论必须标记为等待对应责任角色确认。
7. 历史 Knowledge 只能作为建议背景，不得作为当前 Case 事实。
8. 按平台 `PathAgentResult/v1` JSON 契约返回 `summary`、`options`、`recommendation`、`evidence_gaps` 和恰好三条 `role_reports`。选项 id 必须严格为 `A`、`B`；全部面向人的标题、描述、判断和报告必须使用中文。每条角色报告须为完整中文句子，使用规定前缀，同时提到 A、B，并保留人类审批边界。

不得代表主计划、研发、供应经理或 Case Owner 作出决定，不得删除已编译 Policy 的要求，也不得连接或修改 ERP、库存、订单、CRM 或客户系统。
