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
  "kind": "policy | knowledge",
  "id": "稳定业务 ID",
  "version": "发布版本",
  "title": "人可读名称",
  "status": "published"
}
```

### 2.1 Policy

Policy 初版只包含结构化 `selector` 和 `requirements.commitments`。`selector` 只接受 `case_type` 与 `path_definition`，每个字段都必须命中；缺少字段视为不适用，不交给 LLM 猜测。每个 Commitment 同时声明 `role`、评审范围、依赖关系及 `role_report.dimension/sentence_prefix`。这些报告契约由命中的 Policy 编译并随逐 Path Manifest 快照冻结，Path Agent 不得自行增删角色。

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
├── path-options.json # 可选；由 Skill 拥有的 Path 候选，而非框架默认值
├── tools.json        # 可选；随 Manifest 冻结的只读模拟查询
├── scripts/          # 可选；确定性脚本
├── references/       # 可选；按需加载的参考资料
└── assets/           # 可选；模板或输出资源
```

这样可以直接复用已有 Skill 文件夹，也能让不同 Agent Runtime 使用同一份能力。`SKILL.md` frontmatter 始终只包含标准的 `name` 和 `description`。

Path 与 Skill 的确定性关系单独放在 `capabilities/builtin/skill-bindings.json`。它有两种用途：

- 读取标准 `SKILL.md` 的 `name` 和 `description`；
- Case-level orchestration Skill 用 binding selector 精确命中一个 `case_type`，并在同一 Skill 文件夹的 `paths.json` 中拥有可以探索的 `1..N` 条 Path；
- Path-level execution Skill 用同时包含 `case_type` 与 `path_definition` 的 selector 注入某一条 Path；
- 对整个 Skill 文件夹计算 SHA-256，任一脚本、参考资料或资产变化都会产生新版本摘要；
- 冻结 `SKILL.md` 正文和文件清单，供审计与 Adapter 消费。
- 若存在 `path-options.json` 或 `tools.json`，CapabilityRegistry 会校验其契约并把内容随 Skill payload 一起冻结；Path Agent 不从框架或 Demo Case 复制一份候选定义。

Demo 的 `shortage-response-planning/paths.json` 是提拉、替代、拆分三条定义的唯一来源，`SKILL.md` 只说明如何根据当前 Case 解释和排序它们。`material-substitution-analysis/path-options.json` 是 A（MCU-X7A）和 B（MCU-X7B）的唯一机器可读来源；同包 `tools.json` 提供物料主数据、供应快照和客户接受度的只读模拟查询。角色 Skill 定义分析方法；Policy 的 Commitment 是报告角色、维度、句首、人类责任与依赖的唯一结构化来源。

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
  -> CapabilityRegistry 合并 builtin 与 local 层
  -> 按 case_type 命中 orchestration Skill，并读取其 paths.json
  -> Planner 为 Skill 声明的全部 Path 生成 rationale 和排序
  -> 每条 Path 必须匹配 Path-level execution Skill 与强制 Policy
  -> 再解析该 Path 的全部 Skill / Policy / Knowledge
  -> Manifest 按 Path 冻结资产正文、版本、摘要和 compiled_policy
  -> Owner 批准 Decision Layer
  -> CaseService 只按 frozen compiled_policy 创建 CommitmentDAG
```

页面中的“查看执行层与能力快照”会以 Case Owner 身份读取 `GET /api/cases/CM-2026-014/capabilities`，展示本轮实际冻结的三类资产；该内容和 Manifest 本身对其他角色隐藏。批准 Manifest 后，主计划与研发因没有前置依赖而并行进入 `PENDING` 并投递到各自 Inbox；本人批准后才转为 `READY`。供应经理起初为 `BLOCKED`，仅在两项前置节点都 `READY` 后转为 `PENDING`。这些依赖来自两个 Policy 的编译结果，不是 UI 中的硬编码剧情。

## 4. 开发者接入自己的本地能力

这里的 `local` 首先表示“新增开发者自己的能力”，不是要求复制或覆盖仓库中的同名文件。

默认目录 `.agentic-cm/capabilities/` 已被 Git 忽略。一个完整的本地能力包可以是：

```text
.agentic-cm/capabilities/
├── skill-bindings.json
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

平台不会仅根据正文自然语言猜测业务 Path。一个能为缺料 Case 提出多条 Path 的 orchestration Skill，应在 Skill 文件夹中增加 `paths.json`：

```json
{
  "schema_version": 1,
  "paths": [
    {
      "id": "SupplyExpediting",
      "title": "供应提拉",
      "description": "评估供应与物流加速方案。"
    }
  ]
}
```

`skill-bindings.json` 只负责说明什么 Case 会命中这个 Skill：

```json
{
  "schema_version": 1,
  "bindings": {
    "my-shortage-planning": {
      "selector": {
        "case_type": ["ORDER_DELIVERY_RISK"]
      }
    }
  }
}
```

拥有 `paths.json` 的 Skill 必须通过 binding 精确绑定一个 `case_type`，所以不同 Case 类型自然拥有不同 Path 集合。`paths.json` 写一条，Manifest 就只有一条；写三条，Manifest 必须包含三条。真正进入探索的子集由 Owner 在 Manifest Review 中单选或多选。

每条声明的 Path 还必须命中至少一个 Path-level execution Skill 和至少一个能编译出 Commitment 的 Policy；任意一条缺失都会让本次编排整体 fail closed，避免 Skill 声明三条但 Manifest 静默缩水。Path-level Skill、Policy 和 Knowledge 引用 Path 时都必须同时声明 `case_type` 与 `path_definition`，避免不同 Case 类型的同名 Path 串用能力。

### 4.2 接入自己的 Policy

在本地 `policies/` 下放置任意文件名的 JSON。系统不使用文件名识别 Policy，而使用文件内容中的 `(kind, id)`：

```json
{
  "schema_version": 1,
  "kind": "policy",
  "id": "POL-MY-COMPANY-REGION-001",
  "version": "1.0.0",
  "title": "目标地区认证检查要求",
  "status": "published",
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

输出中的本地资产应标记为 `source=local`。重启 API 并重置 Demo 后，新 Manifest 才会解析并冻结新的资产正文、版本和摘要；已经存在的 Manifest 不会因本地文件变化而被静默修改。

如需把本地能力放到仓库外：

```bash
export AGENTIC_CM_LOCAL_CAPABILITIES_DIR=/absolute/path/to/my-capabilities
```

秘密信息不得写进 Skill、Policy 或 Knowledge；凭证仍应由运行时配置注入。

## 5. 当前边界

这套底座当前完成的是资产契约、分层加载、匹配、Policy 编译、Manifest 快照、API 展示、本地扩展与可选替换。Live Model Adapter、向量检索、Knowledge 发布审核、Skill/Policy 管理后台和生产级签名不在本轮范围；后续接入时应继续消费同一份冻结快照，而不是绕开平台重新检索强制规则。
