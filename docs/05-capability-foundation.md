# 初版能力底座：Policy、Skill 与 Knowledge

## 1. 三者不是同一种“提示词”

初版将能力资产分成三类，并让它们拥有不同的执行权力：

| 资产 | 回答的问题 | 运行方式 | 能否改变强制责任 |
| --- | --- | --- | --- |
| Policy | 这个 Case 在这条 Path 上必须遵守什么 | 平台按结构化字段匹配并确定性编译 | 可以，且 Agent 不得删除 |
| Skill | Agent 应如何完成一个认知任务 | Adapter 将版本化方法注入一次 Agent run | 不可以 |
| Knowledge | 有哪些带来源的材料可辅助当前判断 | 按适用范围检索，作为建议性上下文 | 不可以 |

`Experience` 不再与 Knowledge 并列。它是 `knowledge_type=experience` 的一种 Knowledge；后续还可以加入标准说明、产品资料、案例摘要等类型。无论类型如何，Knowledge 都不能替代当前 Case 事实或人的 Commitment。

## 2. 文件契约

内置资产位于 `capabilities/builtin/{policies,skills,knowledge}`。Policy 与 Knowledge 使用平台需要确定性解释的 JSON 契约：

```json
{
  "schema_version": 1,
  "id": "稳定业务 ID",
  "version": "发布版本",
  "title": "人可读名称"
}
```

资产类型由所在的 `policies/` 或 `knowledge/` 目录唯一确定；进入这些目录即表示发布，不再重复声明 `kind` 或固定的 `status=published`。

### 2.1 Policy

Policy 资产初版只包含结构化 `selector` 和 `requirements.commitments`。`selector` 只接受 `case_type` 与 `path_definition`，每个字段都必须命中；缺少字段视为不适用，不交给 LLM 猜测。每个 Commitment 只声明 `id`、`role`、`review_dimension` 与可选的 `depends_on`。解析期验证依赖与顺序后，Manifest 只记录 Policy 的 `id/version/digest`；批准与执行时校验引用并确定性编译 Commitments，Path Agent 不得自行增删角色。

当前 Demo 的四个实例是：

- `POL-SUBSTITUTION-3`：要求主计划与研发分别确认候选 A/B；
- `POL-CUSTOMER-2`：要求供应经理在供应与技术承诺之后确认地区认证和客户接受度。
- `POL-EXPEDITING-1`：要求采购与供应协同确认供应商产能和供应日期，再由物流确认运输与到货日期；
- `POL-ORDER-SPLIT-1`：要求主计划确认可用数量和交付批次，再由供应经理确认客户接受度与剩余承诺。

编译器合并责任节点及其报告契约，并校验未知依赖、DAG 环和同一节点的冲突。无法判定时启动失败，即 fail closed。

初版刻意不提供以下通用字段：

- `risk_level`：只有平台存在可信的风险分级来源，而且同一 Policy 确实需要按风险分级时再加入；当前 Demo 没有风险评估流程；
- `evidence`：只有 Evidence 成为可提交、校验和追踪状态的一等对象时再加入；当前先由 Commitment 的评审范围表达责任；
- `constraints`：不提供任意键值字典。真正需要平台执行的参数应进入有类型的 Path 配置，并有对应代码和测试。

判断原则是：没有真实生产者、消费者和可验证行为的字段，不进入初版契约。

### 2.2 Skill

Skill 复用通行的文件夹约定；只有需要被平台确定性消费的候选和只读 Tool 使用小型有类型 JSON 契约：

```text
material-substitution-analysis/
├── SKILL.md          # 必需；YAML name/description + Markdown 指令
├── bundle.json       # 可选；Skill Bundle 直接包含的 Atomic Skill ID
├── path-options.json # 可选；由 Skill 拥有的 Path 候选，而非框架默认值
├── tools.json        # 可选；随 Manifest 冻结的只读模拟查询
├── scripts/          # 可选；确定性脚本
├── references/       # 可选；按需加载的参考资料
└── assets/           # 可选；模板或输出资源
```

这样可以直接复用已有 Skill 文件夹，也能让不同 Agent Runtime 使用同一份能力。`SKILL.md` frontmatter 始终只包含标准的 `name` 和 `description`。Skill 不绑定 Case Type 或 Path；适用性写在描述和指令里，由 Orchestrator 结合 Case 上下文选择。

平台不在 frontmatter 增加 `type`、`level` 或 `assigned_via`。Skill 层级由文件结构唯一推导：有 `bundle.json` 的 Skill 是 Skill Bundle，没有 `bundle.json` 的是 Atomic Skill。Case 类型及其候选 Path 不属于 Skill，由独立的 `case-types/<name>/paths.json` 声明。`bundle.json` 只保留最小成员关系：

```json
{
  "schema_version": 1,
  "members": ["material-substitution-engineering-review"]
}
```

Bundle 成员必须存在且不能再拥有 `bundle.json`。同一 Atomic Skill 可以被多个 Bundle 复用。Orchestrator 只能看见 Bundle 与不属于任何 Bundle 的 Atomic Skill；Bundle 成员对 Planner 不可见，但会随所属 Bundle 一起冻结到 Path Manifest，供 Path Agent 执行。

Skill 维护归属单独放在 `capabilities/builtin/skill-ownership.json`。它只服务组织资产治理和前台分组，不进入 Skill digest、Manifest、Agent Prompt 或选择算法：

```json
{
  "schema_version": 1,
  "ownership": {
    "material-substitution-analysis": {"maintainer_role": "订单统筹经理"}
  }
}
```

每项 Skill 或 Bundle 只允许一个非空 `maintainer_role`。ownership 引用未知 Skill 时 fail closed；未出现在 ownership 中的 Skill 归入“平台公共能力”。本地 `.agentic-cm/capabilities/skill-ownership.json` 按 Skill ID 覆盖 built-in 项。

Skill loader 读取标准 `SKILL.md` 的 `name` 和 `description`，对整个 Skill 文件夹计算 SHA-256，并冻结正文和文件清单。`path-options.json` 只声明该 Skill 能处理的结构化候选，不再保存 `path_definition`：

```json
{
  "schema_version": 1,
  "options": [
    {"id": "A", "material_id": "MCU-X7A", "title": "同系列替代料 A", "description": "..."}
  ]
}
```

若存在 `tools.json`，CapabilityRegistry 会校验其契约并把内容随 Skill payload 一起冻结；Path Agent 不从框架或 Demo Case 复制一份候选定义。

Demo 的 `case-types/order-delivery-risk/paths.json` 是提拉、替代、拆分三条定义的唯一来源。遍历全部候选、生成 rationale、不得遗漏或发明 Path 是 Orchestrator 的统一规则。`material-substitution-analysis` 作为 Bundle 入口对 Orchestrator 可见，其三个成员继续隐藏。`supply-expediting-analysis` 与 `order-split-analysis` 作为独立 Atomic Skill 可见。角色 Skill 定义分析方法；Policy 的 Commitment 是报告角色、维度、句首、人类责任与依赖的唯一结构化来源。

### 2.3 Knowledge

Knowledge 包含：

- `selector`：Case 类型与 Path 适用范围；
- `source`：来源类型、原 Case、观察时间和审核者；
- `confidence`：置信标记；
- `content`：摘要与观察内容。

Demo 的 `KNOW-2025-041` 来自已关闭 Case，提示“地区认证可能导致末端返工”。它只能帮助 Agent 排序关注点，不能证明本次客户已经接受 B。

## 3. Demo 请求链

```text
Case classification
  -> 平台按 case_type 读取候选 Path Catalog
  -> 平台按 case_type + path_definition 确定性匹配 Policy
  -> CapabilityRegistry 生成隐藏 Bundle 成员的轻量 Skill Catalog
  -> Orchestrator 为每条 Path 选择 Skill 入口并说明理由
  -> 平台校验白名单、展开 Bundle、固定 version/digest
  -> 生成 Manifest，Owner 审批 Path 与 Skill 选择
  -> Path Agent 只加载获批 Path 已冻结的完整 Skill
  -> Policy 编译出的业务角色分别评审和承诺
```

Manifest Review 中的“查看完整 Manifest YAML”会以 Case Owner 身份读取 `GET /api/cases/CM-2026-014/manifest.yaml`，展示全部 Path、每条 Path 的 Skill 选择理由、Bundle 展开成员以及 Policy、Knowledge 引用；资产全文按引用动态解析，不进入 Manifest。批准 Manifest 后，主计划与研发因没有前置依赖而并行进入 `PENDING` 并投递到各自 Inbox；本人批准后才转为 `READY`。供应经理起初为 `BLOCKED`，仅在两项前置节点都 `READY` 后转为 `PENDING`。这些依赖来自引用 Policy 编译出的 Commitments，不是 UI 中的硬编码剧情。组织资产页按单一维护 Role 分组 Skill，不再展示 `Case Type → Path` 树。

## 4. 开发者接入自己的本地能力

这里的 `local` 首先表示“新增开发者自己的能力”，不是要求复制或覆盖仓库中的同名文件。

默认目录 `.agentic-cm/capabilities/` 已被 Git 忽略。一个完整的本地能力包可以是：

```text
.agentic-cm/capabilities/
├── case-types/
│   └── my-case-type/
│       └── paths.json
├── skill-ownership.json
├── skills/
│   └── regional-certification-check/
│       ├── SKILL.md
│       ├── scripts/       # 可选
│       ├── references/    # 可选
│       └── assets/        # 可选
├── policies/
│   └── any-filename-is-allowed.json
└── knowledge/
    └── my-private-note.json
```

仓库已经提供一套独立示例：[examples/local-capabilities](../examples/local-capabilities/README.md)。直接接入：

```bash
mkdir -p .agentic-cm/capabilities
cp -R examples/local-capabilities/. .agentic-cm/capabilities/
```

### 4.1 接入自己的 Skill

新 Skill 不需要与任何内置 Skill 同名。只需遵守标准 Skill 约定：

1. 在 `.agentic-cm/capabilities/skills/<skill-name>/` 放入完整 Skill 文件夹；
2. 文件夹名必须等于 `SKILL.md` frontmatter 的 `name`；
3. `SKILL.md` 至少包含字符串类型的 `name` 和 `description`；
4. 可原样保留已有的 `scripts/`、`references/`、`assets/`、`agents/` 等资源。

Skill 不需要绑定 Case Type 或 Path。新增或本地覆盖 Case 类型时，应在 `case-types/<name>/paths.json` 中声明完整候选集：

```json
{
  "schema_version": 1,
  "case_type": "ORDER_DELIVERY_RISK",
  "title": "订单交付风险",
  "paths": [
    {
      "id": "SupplyExpediting",
      "title": "供应提拉",
      "description": "评估供应与物流加速方案。"
    }
  ]
}
```

`skill-ownership.json` 只声明展示用的维护 Role，不决定 Orchestrator 能否看见或选择该 Skill：

```json
{
  "schema_version": 1,
  "ownership": {
    "my-expediting-analysis": {
      "maintainer_role": "供应经理"
    }
  }
}
```

每个 Catalog 显式声明一个 `case_type`。本地同 `case_type` Catalog 会整体覆盖内置 Catalog，不逐 Path 合并；`paths.json` 写一条，Manifest 就只有一条，写三条则 Manifest 必须包含三条。真正进入探索的子集由 Owner 在 Manifest Review 中单选或多选。

Orchestrator 必须为每条 Catalog Path 选择至少一个白名单 Skill 入口，并提供非空中文理由；每条 Path 还必须命中至少一个能编译出 Commitment 的 Policy。Skill Catalog 为空或任一 Path 缺少强制 Policy 时，本次编排整体 fail closed。Policy 和 Knowledge 引用 Path 时必须同时声明 `case_type` 与 `path_definition`，避免不同 Case 类型的同名 Path 串用治理资产。Skill 不再使用 selector。

### 4.2 接入自己的 Policy

在本地 `policies/` 下放置任意文件名的 JSON。目录确定资产类型，系统使用文件内容中的 `id` 识别 Policy：

```json
{
  "schema_version": 1,
  "id": "POL-MY-COMPANY-REGION-001",
  "version": "1.0.0",
  "title": "目标地区认证检查要求",
  "selector": {
    "case_type": ["ORDER_DELIVERY_RISK"],
    "path_definition": ["MaterialSubstitution"]
  },
  "requirements": {
    "commitments": []
  }
}
```

只要 `selector` 命中，新增 Policy 就会与内置 Policy 一起编译。责任节点依赖缺失、DAG 成环或同一节点定义冲突都会 fail closed。

### 4.3 接入自己的 Knowledge

在本地 `knowledge/` 下放置任意文件名的 JSON，并使用新的 `id`。必须保留 `selector`、`source`、`confidence` 和 `content`，确保 Agent 能区分适用范围、证据来源和可信程度。

Knowledge 命中后会加入 Agent 上下文，但永远不会生成强制责任节点，也不能替代当前 Case 事实。

### 4.4 新增与替换的身份规则

| 本地资产 | 身份 | 与内置身份不同 | 与内置身份相同 |
| --- | --- | --- | --- |
| Skill | frontmatter `name` | 新增 Skill | 有意替换同名 Skill |
| Policy | `kind + id` | 新增 Policy | 有意替换同 ID Policy |
| Knowledge | `kind + id` | 新增 Knowledge | 有意替换同 ID Knowledge |

因此本地文件名无需与仓库文件名一致。Skill 的“文件夹名等于 name”是标准 Skill 自身的结构要求，不是与仓库内置文件对齐。

### 4.5 验证与生效

```bash
PYTHONPATH=backend .venv/bin/python -m agentic_cm.capabilities validate
PYTHONPATH=backend .venv/bin/python -m agentic_cm.capabilities resolve
```

输出中的本地资产应标记为 `source=local`。重启 API 并重置 Demo 后，新 Manifest 才会记录新的版本和摘要；已有 Manifest 若找不到完全一致的 `id/version/digest` 会 fail closed，绝不会静默使用同 ID 的新内容。

如需把本地能力放到仓库外：

```bash
export AGENTIC_CM_LOCAL_CAPABILITIES_DIR=/absolute/path/to/my-capabilities
```

秘密信息不得写进 Skill、Policy 或 Knowledge；凭证仍应由运行时配置注入。

## 5. 当前边界

这套底座当前完成的是资产契约、分层加载、匹配、Policy 依赖验证、Path 自包含 Manifest、API 展示、本地扩展与可选替换。Live Model Adapter、向量检索、Knowledge 发布审核、Skill/Policy 管理后台和生产级签名不在本轮范围；后续接入时应继续消费同一份冻结 Manifest Path，而不是绕开平台重新检索强制规则。
