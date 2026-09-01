---
name: material-substitution-analysis
description: 当已批准 Path 需要比较物料替代候选时使用；编排技术、供应和客户接受度评审，形成可供责任角色批准的中文方案。
---

# 物料替代分析

1. 先读取 `/case/snapshot.json`、`/case/path.json`、`/evidence/authorized-options.json` 和 `/evidence/required-role-reports.json`。如存在，再读取 `/case/human-proposal.json`、`/case/previous-solution-revision.json` 与 `/knowledge/context.json`。
2. 读取 `/skills/material-substitution-analysis/bundle.json`，再逐一读取其中列出的成员 Skill；按成员 Skill 的方法分析每个授权候选，并按其要求调用可用的只读 Function Tools。
3. 证据优先级为：当前 Case 与 Function Tool 返回的冻结记录，高于 HumanProposal；HumanProposal 只表达目标偏好；Knowledge 只提供历史背景。后两者都不能替代当前证据或责任角色确认。
4. 比较技术可行性、供应与交付、客户与商务接受度，形成一份中文推荐方案。不得发明未授权候选、未经查询的事实或已确认承诺。
5. 严格按照 `/evidence/required-role-reports.json` 中的角色与维度逐项生成报告，不得遗漏或增加；每份报告都要说明批准理由以及仍待该角色确认的事项。
