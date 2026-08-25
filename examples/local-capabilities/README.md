# 接入自己的本地能力

这个目录是一套可以直接复制的开发者示例，不是对仓库内置文件的改名副本。示例新增了：

- 自定义 Policy：`POL-MY-COMPANY-REGION-001`；
- 自定义 Skill：`regional-certification-check`；
- 自定义 Knowledge：`KNOW-MY-COMPANY-REGION-001`；
- 一份本地 Skill 与 Path 的绑定。

复制到 Git 已忽略的本地能力目录：

```bash
mkdir -p .agentic-cm/capabilities
cp -R examples/local-capabilities/. .agentic-cm/capabilities/
```

验证并查看 Demo Case 实际解析结果：

```bash
PYTHONPATH=backend .venv/bin/python -m agentic_cm.capabilities validate
PYTHONPATH=backend .venv/bin/python -m agentic_cm.capabilities resolve
```

重启 API 并重置 Demo 后，能力快照中应同时出现内置资产与这三个 `source=local` 的新增资产。

注意：

- Policy/Knowledge 的 JSON 文件名可以任意取，系统以文件内容中的 `kind + id` 识别资产；
- 每个 Policy Commitment 必须提供 `role_report.dimension` 与 `role_report.sentence_prefix`；平台会把它与责任角色、依赖一起冻结进 Manifest，并据此约束 Path Agent 报告；
- Skill 不需要与仓库中的任何 Skill 同名，但按照标准约定，其文件夹名必须等于 `SKILL.md` frontmatter 的 `name`；
- 新 Skill 必须在本地 `skill-bindings.json` 中绑定适用的 Case/Path 上下文，否则会被加载但不会自动加入 Manifest；
- 只有故意使用与内置资产相同的身份时，才表示替换内置资产。
