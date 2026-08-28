# Agent 自主选择与 Role 维护 Skill 设计

## 目标

将 Policy 的确定性适用关系与 Skill 的 Agent 自主选择彻底分开：

- Policy 继续通过 `case_type + path_definition` selector 由平台确定性匹配，并编译为必须执行的 CommitmentDAG；
- Skill 不再绑定 Case Type 或 Path。Orchestrator 根据当前 Case、候选 Path 与 Skill 描述自主选择本次需要的 Skill；
- 平台校验 Orchestrator 的选择、展开 Bundle，并将精确版本冻结进 Manifest，交由 Case Owner 审批；
- 每个 Skill 或 Skill Bundle 只配置一个 `maintainer_role`，用于组织资产治理和前台展示，不影响 Agent 选择；
- 组织资产页按维护 Role 展示 Skill，不再按 `Case Type → Path` 挂载，避免暗示 Skill 只能服务某条 Path。

本次设计不改变治理边界：Agent 只分析、选择方法并提出方案；人类批准 Manifest 与业务 Commitment；平台负责白名单、状态、权限、依赖、版本和审计。

## 核心概念边界

### Policy

Policy 是平台能够确定性解释的治理资产。它保留 `selector.case_type` 与 `selector.path_definition`，负责声明必须参与的角色、评审维度和依赖。Orchestrator 不能选择、删除或新增 Policy，也不能改变 Policy 编译出的 Commitment。

### Skill

Skill 是 Agent 完成认知任务所采用的方法、指令和资源。Skill 的标准 `SKILL.md` 继续以 `name` 和 `description` 作为发现入口，不包含 Case Type、Path 或维护 Role。

Skill 可以非常通用，也可以针对某个专业场景；“不绑定 Path”不等于“所有 Skill 都必须通用”。适用性由描述和指令表达，由 Orchestrator 结合 Case 上下文判断，而不是由平台业务枚举预先限定。

### Skill Bundle

Skill Bundle 是可复用的 Skill 组合，不属于任何 Path。Bundle 自身是 Orchestrator 可选择的能力入口；内部 Atomic Skill 是实现细节，对 Orchestrator 不可见。平台在选择完成后确定性展开 Bundle，Path Agent 执行 Bundle 入口及其全部成员。

### Maintainer Role

`maintainer_role` 表示组织中负责维护、评审和更新某项 Skill 的主要角色。每项 Skill 或 Bundle 首版只允许一个维护 Role。该字段不是执行授权、Policy 责任角色或当前 Actor 身份，不进入 Agent Prompt，也不改变编排结果。

## 能力目录结构

内置目录调整为：

```text
capabilities/builtin/
├── case-types/
│   └── order-delivery-risk/
│       └── paths.json
├── policies/
├── knowledge/
├── skills/
│   ├── material-substitution-analysis/
│   │   ├── SKILL.md
│   │   ├── bundle.json
│   │   └── ...
│   └── ...
└── skill-ownership.json
```

删除 `skill-bindings.json`。Skill 加载器不再读取或生成 `selector`，CapabilityRegistry 也不再通过 Case 上下文筛选 Skill。

本地目录可以用 `.agentic-cm/capabilities/skill-ownership.json` 覆盖维护归属。built-in 与 local ownership 按 Skill ID 合并；local 同 ID 项覆盖 built-in 项，不要求复制整份 built-in 文件。

## Skill 维护归属契约

`skill-ownership.json` 使用以下结构：

```json
{
  "schema_version": 1,
  "ownership": {
    "material-substitution-analysis": {
      "maintainer_role": "订单统筹经理"
    },
    "material-substitution-engineering-review": {
      "maintainer_role": "研发"
    }
  }
}
```

约束如下：

- `schema_version` 必须为 `1`；
- `ownership` 必须是以 Skill ID 为键的对象；
- 每项只允许一个非空字符串 `maintainer_role`；
- ownership 引用不存在的 Skill 时 CapabilityRegistry fail closed；
- Skill 未出现在最终 ownership 中是合法状态，前台将其归入“平台公共能力”；
- ownership 不进入规范化 Skill 内容、Skill digest、Manifest 或 AgentRun Prompt；面向人类的资产 API 可以把它作为独立治理投影附加到响应中；
- 修改维护 Role 不产生新的 Skill 内容版本，也不使已批准 Manifest 失效。

当前 Demo 尚无独立的组织 Role Catalog，因此首版使用与 Policy、Identity 相同的中文 Role 字符串。未来接入权威组织目录时可以把该值迁移为稳定 Role ID，但不得把 Role 引入 Skill 选择算法。

## Orchestrator Skill Catalog

CapabilityRegistry 需要提供专用的 Orchestrator 投影，而不是直接把面向人类的资产 API 响应发送给模型。

Orchestrator 只看见两类可选择入口：

1. 不属于任何 Bundle 的 Atomic Skill；
2. Skill Bundle。

只要 Atomic Skill 是任一 Bundle 的成员，它就不进入 Orchestrator Skill Catalog。成员仍可被多个 Bundle 复用，也可以在组织资产页查看。

每个 Orchestrator 候选只包含：

```json
{
  "id": "material-substitution-analysis",
  "title": "物料替代分析",
  "description": "分析候选物料的供应、技术和客户接受度，形成可评审方案。",
  "kind": "bundle"
}
```

投影明确排除：

- `maintainer_role`；
- Bundle `members`；
- 完整 `SKILL.md` 正文；
- scripts、references、assets、tools 和 path options；
- Skill selector；
- digest、文件清单及其他仅供平台校验的信息。

这样既减少 Orchestrator 上下文，也防止 Role 归属和 Bundle 实现细节影响语义选择。Bundle 的 `description` 必须独立说明它能完成什么、何时应使用、所需输入、预期输出和不适用情形。

## Planner 输入与输出

Planner 输入继续包含 Case 上下文和 Case Type Catalog 声明的完整候选 Path，并新增独立的轻量 `skill_catalog`。Policy 仍由平台按 Path 解析；Planner 可以看到 Policy 编译出的必要评审维度，以理解方案要求，但不能选择 Policy。

Planner 对每条 Path 返回：

```json
{
  "definition": "MaterialSubstitution",
  "rationale": "该方向可以针对当前缺料评估替代候选。",
  "skills": [
    {
      "id": "material-substitution-analysis",
      "reason": "需要同时分析供应覆盖、技术可行性和客户准入。"
    }
  ]
}
```

平台在模型输出后确定性校验：

- Catalog 中每条 Path 必须出现且只能出现一次；
- 每条 Path 至少选择一个 Skill 入口；
- Skill ID 必须来自本次传给 Planner 的白名单；
- 同一 Path 不得重复选择同一个入口；
- Bundle 成员即使被模型猜出，也因不在白名单而被拒绝；
- `reason` 必须是非空、面向人的中文说明；
- Policy 必须已经匹配并至少编译出一个 mandatory Commitment；
- 任一校验失败沿用结构化输出修复机制；最终仍失败则只保留 AgentRun trace，不创建或修改 Manifest。

平台不尝试用规则判断模型选择的 Skill 在业务上是否“最相关”。相关性属于 Agent 提案和 Owner 审批范围；平台只保证选择来自授权资产、结构完整、版本可解析且可审计。

## Bundle 展开与 Manifest 冻结

Planner 通过后，平台根据当前 CapabilityRegistry 展开每个选中的入口：

- Atomic Skill 解析为入口自身；
- Skill Bundle 解析为 Bundle 自身及 `bundle.json` 声明的全部成员；
- Bundle 成员必须存在、必须是 Atomic Skill，且 Bundle 不能循环嵌套；
- 同一成员可被多个 Bundle 复用；同一 Path 的最终执行集合按 Skill ID 去重；
- 所有入口和成员都冻结 `id + version + digest`。

ManifestPath 用选择记录保存“Agent 选择”与“平台展开”两层事实：

```yaml
skill_selections:
  - entrypoint:
      id: material-substitution-analysis
      version: 8d2cbd53c12a
      digest: sha256:...
    reason: 需要同时分析供应覆盖、技术可行性和客户准入。
    members:
      - id: material-substitution-engineering-review
        version: 4bc1a02e7d11
        digest: sha256:...
      - id: material-substitution-master-planning-review
        version: 26a33e67d402
        digest: sha256:...
```

Atomic Skill 的 `members` 为空。`entrypoint` 与 `members` 都是不可变引用，不复制 Skill 正文、维护 Role 或 Bundle 元数据。审批或执行时任一引用的 version/digest 不匹配都 fail closed。

Case Owner 在 Manifest Review 中可以查看每个入口的选择理由，并展开查看 Bundle 成员。这里表达的是“本次 Case 的这条 Path 实际采用了什么”，不构成组织资产层面的永久 Path 绑定。

## Path Agent 执行

Path Agent 不重新访问完整 Skill Library，也不重新选择 Skill。平台只解析已批准 ManifestPath 的 `skill_selections`：

1. 校验入口与成员的精确引用；
2. 加载入口及成员的完整 `SKILL.md`；
3. 加载被引用 Skill 自带的工具和资源；
4. 结合当前 Path、Case 冻结事实、匹配 Policy、Knowledge 和上一版方案组装最小 `PathAgentContext`；
5. 执行并继续校验候选、角色报告和输出契约。

Role ownership 不进入上述过程。某个 Skill 由“研发”维护，不意味着只有研发 Actor 能触发它，也不意味着它只能生成研发 Commitment。

## 组织资产 API 与前台

`GET /api/capabilities` 是面向人类的资产目录，可以返回每项 Skill 的：

- `maintainer_role`；
- `kind`；
- Bundle 成员引用；
- 标准 Skill 描述、正文、文件、版本、来源和 digest。

Skills 页面取消 `Case Type → Path → Skill` 树，改为按 `maintainer_role` 分组：

```text
研发
└── 候选料技术可行性分析 · ATOMIC SKILL

主计划
└── 候选料供应覆盖与交期分析 · ATOMIC SKILL

供应经理
└── 候选料客户准入与商务影响分析 · ATOMIC SKILL

订单统筹经理
└── 物料替代综合分析 · SKILL BUNDLE
    ├── 候选料技术可行性分析 · 研发维护
    ├── 候选料供应覆盖与交期分析 · 主计划维护
    └── 候选料客户准入与商务影响分析 · 供应经理维护

平台公共能力
└── 未配置维护 Role 的 Skill
```

每项 Skill 只在自己的 Role 分组中渲染一次完整卡片。Bundle 卡片可以列出内部成员名称与各自维护 Role，但只作为组合引用，不重复渲染成员全文。搜索匹配 Role、Skill 名称、ID、描述和 Bundle 成员名称。

Policy 页面仍展示 Case Type、Path selector 和 Commitment；Knowledge 页面保持现有适用范围展示。本设计只取消 Skill 的 Path 归属表达。

## 数据流

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

## 失败处理与审计

- Skill 或 Bundle 结构非法、Bundle 成员缺失、ownership 引用未知 Skill：CapabilityRegistry 启动或校验失败；
- 没有任何 Orchestrator 可见 Skill 入口：Manifest 生成在模型调用前失败；
- Planner 返回未知 Skill、Bundle 成员、重复选择、空理由或某条 Path 无 Skill：先执行一次可审计修复，仍失败则本次 Orchestrator run 失败；
- Bundle 展开或引用冻结失败：不保存 Manifest，不产生业务事件；
- Owner 拒绝或要求修改 Skill 选择：沿用 Manifest 修订流程，生成新 revision；
- 已批准 Manifest 的 Skill 内容发生变化：旧引用失配，Path 执行 fail closed，要求重新生成或修订 Manifest；
- 仅修改 `maintainer_role`：不影响已批准 Manifest，也不触发重新编排。

AgentRun trace 记录提供给 Planner 的可见 Skill 入口引用、模型返回的选择与理由、Bundle 展开结果和校验失败原因。Trace 不记录凭证、隐藏推理或不必要的完整 Skill 正文。

## 迁移策略

新写入只使用 Agent 自主选择模型，不保留 `skill-bindings.json` 与新模型并行运行：

1. 删除 built-in 与示例目录中的 `skill-bindings.json`；
2. Skill loader 删除 binding/selector 注入逻辑；
3. CapabilityRegistry 将全部合法 Skill 纳入组织资产库，并单独生成 Orchestrator 可见入口；
4. 当前 `material-substitution-analysis` 作为 Bundle 入口可见，其三个成员继续隐藏；
5. 当前 `supply-expediting-analysis` 与 `order-split-analysis` 作为独立 Atomic Skill 可见；
6. 新增 `skill-ownership.json`，为 Demo 的 Bundle 和 Atomic Skill配置单一维护 Role；
7. Planner 输出和 ManifestPath 迁移到 `skill_selections`；
8. Repository 继续读取已有 Manifest 的平铺 `skills` 引用，但旧 Manifest 不生成选择理由；旧引用通过 version/digest 校验后仍可执行；
9. 旧持久化快照内已经冻结的 selector 只用于兼容读取，不参与新 Manifest 生成；
10. 文档和前端删除 Skill “已绑定场景”“Case Type/Path 层级”等表述。

不在本次设计中引入能力标签、向量检索或 Role-based Skill filtering。Skill 数量增长到轻量目录明显影响上下文或选择质量时，再在 Orchestrator 之前增加检索层；检索结果仍必须遵守同一白名单、冻结和审批契约。

## 测试与验收

后端测试覆盖：

- Skill 不再包含 selector，删除 `skill-bindings.json` 后能力校验通过；
- Policy 仍按 `case_type + path_definition` 确定性匹配并编译相同 Commitment；
- Orchestrator Catalog 只包含 Bundle 和非成员 Atomic Skill；
- Bundle 成员及 `maintainer_role` 不出现在 Planner Prompt；
- 同一 Atomic Skill 被多个 Bundle 引用时仍不单独暴露，Bundle 分别可以正确展开；
- Planner 可为不同 Path 自主选择相同 Skill 入口；
- 未知 Skill、猜测的 Bundle 成员、重复 ID、空理由和空选择均 fail closed；
- Manifest 冻结入口、理由、成员 version/digest，并在引用失配时拒绝审批或执行；
- Path Agent 只读取已批准 Manifest 的 Skill，不重新访问完整 Skill Catalog；
- ownership 合并、local 覆盖、未知 Skill 和未分配 Skill行为正确；
- 修改 ownership 不改变 Skill digest，也不使 Manifest 引用失效；
- 旧平铺 Skill 引用 Manifest 保持读取兼容。

前端测试覆盖：

- Skills 页面不再出现 Case Type 与 Path 层级；
- Skill 按单一维护 Role 分组；
- 未分配 Skill 显示在“平台公共能力”；
- Bundle 卡片展示成员名称与成员维护 Role，但不重复完整卡片；
- 页面不再显示 Skill selector 或“未绑定场景”；
- 搜索可以匹配 Role、Skill、Bundle 及成员；
- Manifest Review 展示本次 Skill 选择理由和可展开的 Bundle 成员。

完整验收执行 backend tests、capability validation、frontend lint、frontend tests 和 frontend build，并针对 Skills 资产页与 Manifest Review 进行浏览器检查。

## 非目标

- 不让 Role 决定 Orchestrator 可以看到或选择哪些 Skill；
- 不让 Agent 选择 Policy、Commitment 或业务审批角色；
- 不允许 Path Agent 在 Owner 批准后重新选 Skill；
- 不把 Bundle 成员暴露给 Orchestrator；
- 不把 Skill 永久挂载到 Case Type 或 Path；
- 不建设通用 Role 管理、RBAC、Skill 编辑器、向量检索或多维护人协作流程；
- 不要求本次把所有专业 Skill 改写为完全领域无关的通用方法。
