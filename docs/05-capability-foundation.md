# 能力底座

Policy、Skill、Knowledge 不是同一种提示词。

| 资产 | 作用 | Agent 能否改强制责任 |
|---|---|---|
| Policy | 结构化 `selector` + `requirements.commitments` | 否 |
| Skill | 认知方法；可选 Bundle、path-options、只读 tools | 否 |
| Knowledge | 有来源的建议材料 | 否 |

内置目录：`capabilities/builtin/{policies,skills,knowledge,case-types}`。本地覆盖：`.agentic-cm/capabilities/`，同 id 整份替换。模板见 `examples/local-capabilities/`。

## Case Type Catalog

`case-types/<name>/paths.json` 是 Path 定义的唯一来源。Skill 不绑定 Path。本地同 `case_type` Catalog 整体覆盖内置，不按 Path 合并。

## Skill

```text
material-substitution-analysis/
├── SKILL.md           # YAML name/description + Markdown
├── bundle.json        # 可选；成员必须是 atomic Skill
├── path-options.json  # 可选；授权给 Path Agent 的候选
└── tools.json         # 可选；冻结的只读模拟查询
```

有 `bundle.json` 的是 Bundle。Orchestrator 只能选 Bundle 或非成员 Atomic Skill；成员随入口冻结进 `skill_selections`。

`skill-ownership.json` 只用于资产页分组，不进 digest、Manifest 或 Prompt。

## 解析

Manifest 只存 `AssetRef`。批准和执行时 `resolve_manifest_path` 按 id/version/digest 精确匹配，失败则要求重新生成 Manifest。
