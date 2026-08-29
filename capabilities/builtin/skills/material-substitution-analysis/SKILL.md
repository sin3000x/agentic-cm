---
name: material-substitution-analysis
description: 比较已批准物料替代 Path 的授权候选，形成覆盖技术、供应和客户接受度的评审方案。
---

# 物料替代分析

1. 仅分析 `authorized_options`，每个候选恰好生成一个选项，不得新增、遗漏或改写 id。
2. 使用 `tool_results` 中每个工具的全部候选记录，并应用 Bundle 内三个专业分析 Skill。
3. 分别比较技术、供应与交付、客户与商务接受度，说明收益、风险和假设；无当前证据支持的判断列入 `assumptions` 或 `evidence_gaps`。
4. `human_proposal` 只提供目标偏好，Knowledge 只提供历史背景，两者都不能替代当前证据或责任角色确认。
5. 为 `required_role_reports` 中每个契约生成一条报告，按对应专业 Skill 比较全部候选并指出待确认事项。
