"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? `http://localhost:${process.env.AGENTIC_CM_API_PORT ?? 8000}`;

const cases = [
  { id: "CM-2026-014", title: "订单预计延期", status: "处理中", active: true },
  { id: "CM-2026-012", title: "供应商交付异常", status: "阻塞" },
  { id: "CM-2026-015", title: "替代料认证缺口", status: "待确认" },
  { id: "CM-2026-006", title: "华南仓到货差异", status: "已关闭" },
];

const stages = ["Case 受理", "Manifest 评审", "Path 探索", "专业承诺", "最终决策", "结果验证"];

const demoIdentities = [
  { name: "陈澄", role: "订单履行经理", avatar: "陈" },
  { name: "王淼", role: "主计划", avatar: "王" },
  { name: "林乔", role: "研发", avatar: "林" },
  { name: "赵宁", role: "一线经理", avatar: "赵" },
];

const commitmentCopy: Record<string, string> = {
  SUPPLY: "确认 A / B 供应可行性",
  TECH: "确认 A / B 技术可行性",
  CUSTOMER: "确认客户接受度与整体建议",
};

type CapabilityAsset = {
  id?: string;
  title?: string;
  version?: string;
  purpose?: string;
  instructions?: string[];
  requirements?: { commitments?: Array<{ role: string }> };
  content?: { summary?: string };
  resolved_ref: { id: string; version: string; source: string; digest: string };
};

type CapabilityDetails = {
  snapshot_status: string;
  assets: {
    policies: CapabilityAsset[];
    skills: CapabilityAsset[];
    knowledge: CapabilityAsset[];
  };
};

type ManifestPath = {
  id: string;
  definition: string;
  title: string;
  rationale: string;
  selected: boolean;
};

type CapabilitySnapshot = {
  policies: Array<{ id: string }>;
  skills: Array<{ id: string }>;
  knowledge: Array<{ id: string }>;
  compiled_policy: { commitments: Array<{ id: string; depends_on?: string[] }> };
};

type CommitmentNode = {
  id: string;
  role: string;
  node_type: string;
  status: "BLOCKED" | "PENDING" | "READY" | "COMMITTED" | "STALE";
  depends_on: string[];
  path_id: string;
};

function CapabilityPanel({ details }: { details: CapabilityDetails }) {
  const groups = [
    { key: "policies" as const, label: "POLICY · 强制责任", note: "由平台结构化匹配并编译为 CommitmentDAG 责任节点" },
    { key: "skills" as const, label: "SKILL · 认知方法", note: "由 Agent Adapter 使用，不能代替业务审批" },
    { key: "knowledge" as const, label: "KNOWLEDGE · 建议材料", note: "带来源的历史观察，不是当前 Case 事实" },
  ];
  return (
    <section className="capabilityPanel" aria-label="Manifest 能力快照">
      <div className="capabilityHeader">
        <span><strong>Execution Layer · 能力快照</strong><small>{details.snapshot_status === "frozen" ? "已随 Manifest 冻结" : "当前预览"}</small></span>
        <em>版本 + SHA-256</em>
      </div>
      <div className="capabilityGroups">
        {groups.map((group) => (
          <div className="capabilityGroup" key={group.key}>
            <div><strong>{group.label}</strong><small>{group.note}</small></div>
            {details.assets[group.key].map((asset) => (
              <article key={asset.resolved_ref.id}>
                <span><b>{asset.title ?? asset.resolved_ref.id}</b><small>{asset.resolved_ref.id} · v{asset.resolved_ref.version}</small></span>
                <span className={`assetSource ${asset.resolved_ref.source}`}>{asset.resolved_ref.source}</span>
                <code>{asset.resolved_ref.digest.slice(7, 19)}</code>
                <p>{asset.purpose ?? asset.content?.summary ?? asset.instructions?.[0] ?? `${asset.requirements?.commitments?.length ?? 0} 个强制责任节点`}</p>
              </article>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Home() {
  const [phase, setPhase] = useState("INTAKE");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [capabilities, setCapabilities] = useState<CapabilityDetails | null>(null);
  const [showCapabilities, setShowCapabilities] = useState(false);
  const [manifestPaths, setManifestPaths] = useState<ManifestPath[]>([]);
  const [capabilitySnapshots, setCapabilitySnapshots] = useState<Record<string, CapabilitySnapshot>>({});
  const [selectedPathIds, setSelectedPathIds] = useState<string[]>([]);
  const [commitmentNodes, setCommitmentNodes] = useState<CommitmentNode[]>([]);
  const [identityIndex, setIdentityIndex] = useState(0);
  const [showInbox, setShowInbox] = useState(false);
  const currentIdentity = demoIdentities[identityIndex];

  function loadManifest(manifest: { paths?: ManifestPath[]; capability_snapshots?: Record<string, CapabilitySnapshot> } | null) {
    const paths = manifest?.paths ?? [];
    setManifestPaths(paths);
    setCapabilitySnapshots(manifest?.capability_snapshots ?? {});
    const substitution = paths.find((path) => path.definition === "MaterialSubstitution");
    setSelectedPathIds(substitution ? [substitution.id] : paths.slice(0, 1).map((path) => path.id));
  }

  useEffect(() => {
    fetch(`${API_BASE}/api/cases/CM-2026-014`)
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((data) => {
        setPhase(data.phase);
        setApproved(data.phase === "PATH_EXPLORATION");
        setCommitmentNodes(data.commitment_nodes ?? []);
        loadManifest(data.manifest);
        if (data.phase === "PATH_EXPLORATION") {
          setSelectedPathIds((data.manifest?.paths ?? []).filter((path: ManifestPath) => path.selected).map((path: ManifestPath) => path.id));
        }
      })
      .catch(() => setMessage("API 尚未连接，当前展示固定演示数据。"));
  }, []);

  async function generateManifest() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/cases/CM-2026-014/orchestrate`, { method: "POST" });
      if (!response.ok) throw new Error("orchestrate failed");
      const data = await response.json();
      setPhase("MANIFEST_REVIEW");
      loadManifest(data.manifest);
      setCapabilities(null);
      setMessage("Orchestrator 已根据 Case 与现有能力生成 Manifest，并冻结适用 Policy。 ");
    } catch {
      setMessage("Manifest 生成失败：请确认本地 API 与 Planner 配置。 ");
    } finally {
      setBusy(false);
    }
  }

  async function approveManifest() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/cases/CM-2026-014/manifest/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selected_path_ids: selectedPathIds }),
      });
      if (!response.ok) throw new Error("approve failed");
      const data = await response.json();
      setManifestPaths(data.manifest.paths);
      setCommitmentNodes(data.commitment_nodes ?? []);
      setApproved(true);
      setPhase("PATH_EXPLORATION");
      setMessage("Manifest 已批准；主计划与研发任务已分别投递到各自 Inbox，等待本人批准。 ");
    } catch {
      setMessage("无法连接本地 API，请先启动 Python 服务。 ");
    } finally {
      setBusy(false);
    }
  }

  async function resetDemo() {
    setBusy(true);
    try {
      const response = await fetch(`${API_BASE}/api/demo/reset`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataset_id: "supply-chain-golden-path-v1" }),
      });
      if (!response.ok) throw new Error("reset failed");
      setApproved(false);
      setPhase("INTAKE");
      setCapabilities(null);
      setShowCapabilities(false);
      setManifestPaths([]);
      setCapabilitySnapshots({});
      setSelectedPathIds([]);
      setCommitmentNodes([]);
      setIdentityIndex(0);
      setShowInbox(false);
      setMessage("Golden Path 演示数据已重置。 ");
    } catch {
      setMessage("重置失败：本地 API 未连接。 ");
    } finally {
      setBusy(false);
    }
  }

  function togglePath(pathId: string) {
    setSelectedPathIds((current) => current.includes(pathId)
      ? current.filter((id) => id !== pathId)
      : [...current, pathId]);
  }

  async function toggleCapabilities() {
    if (showCapabilities) {
      setShowCapabilities(false);
      return;
    }
    setShowCapabilities(true);
    if (capabilities) return;
    try {
      const response = await fetch(`${API_BASE}/api/cases/CM-2026-014/capabilities`);
      if (!response.ok) throw new Error("capabilities failed");
      setCapabilities(await response.json());
    } catch {
      setShowCapabilities(false);
      setMessage("能力快照读取失败：请确认本地 API 已启动。 ");
    }
  }

  async function approveCommitment(node: CommitmentNode) {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(
        `${API_BASE}/api/cases/CM-2026-014/paths/${node.path_id}/commitments/${node.id}/approve`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ actor: currentIdentity.name, role: currentIdentity.role }),
        },
      );
      if (!response.ok) throw new Error("commitment approval failed");
      const data = await response.json();
      setCommitmentNodes(data.commitment_nodes ?? []);
      setMessage(`${currentIdentity.name} 已在 ${currentIdentity.role} Inbox 批准 ${node.id}，节点现为 READY。`);
    } catch {
      setMessage("Inbox 批准失败：请确认当前身份与本地 API 状态。 ");
    } finally {
      setBusy(false);
    }
  }

  const activeStageIndex = approved ? 2 : phase === "INTAKE" ? 0 : 1;
  const currentStage = stages[activeStageIndex];
  const selectedAttemptPathId = manifestPaths.find((path) => path.selected)?.id ?? selectedPathIds[0];
  const activeCommitments = commitmentNodes.filter((node) => node.path_id === selectedAttemptPathId);
  const inboxItems = commitmentNodes.filter(
    (node) => node.role === currentIdentity.role && node.status === "PENDING",
  );

  function commitmentNode(nodeId: string, fallbackRole: string, fallbackStatus: CommitmentNode["status"]) {
    const node = activeCommitments.find((item) => item.id === nodeId) ?? {
      id: nodeId,
      role: fallbackRole,
      node_type: "APPROVAL",
      status: fallbackStatus,
      depends_on: nodeId === "CUSTOMER" ? ["SUPPLY", "TECH"] : [],
      path_id: selectedAttemptPathId ?? "PATH-01",
    };
    const statusLabel = node.status === "PENDING" ? "待本人批准" : node.status;
    return (
      <article className={`dagNode ${node.depends_on.length ? "downstream" : "upstream"} ${node.status.toLowerCase()}`}>
        <span>{statusLabel}</span>
        <h3>{node.role}</h3>
        <p>{commitmentCopy[node.id] ?? "等待责任人确认"}</p>
      </article>
    );
  }

  const orchestrationCard = approved ? (
    <>
      <div className="panelTitle">
        <div><span className="agentIcon">✓</span><span><small>PATH ATTEMPT · ATTEMPT-01</small><h2>物料替代 · 审批 DAG</h2></span></div>
        <span className="version">AWAITING INBOX</span>
      </div>
      <p className="lead">方案 v1 已覆盖候选物料 A / B。主计划与研发任务已并行投递到各自 Inbox；本人批准后节点才会变成 READY。</p>
      <div className="dag" aria-label="Commitment DAG">
        {commitmentNode("SUPPLY", "主计划", "PENDING")}
        {commitmentNode("TECH", "研发", "PENDING")}
        <div className="dagJoin"><i /><i /></div>
        {commitmentNode("CUSTOMER", "一线经理", "BLOCKED")}
      </div>
      <div className="metricStrip">
        <span><strong>2</strong><small>parallel review branches</small></span>
        <span><strong>0</strong><small>preserved commitments</small></span>
        <span><strong>0</strong><small>re-review avoided</small></span>
      </div>
      <button className="linkButton capabilityToggle" onClick={toggleCapabilities}>{showCapabilities ? "收起能力快照 ↑" : "查看本次能力快照 →"}</button>
      {showCapabilities && capabilities && <CapabilityPanel details={capabilities} />}
    </>
  ) : phase === "INTAKE" ? (
    <>
      <div className="panelTitle">
        <div><span className="agentIcon">✦</span><span><small>ORCHESTRATOR</small><h2>从 Case 组装 Manifest</h2></span></div>
        <span className="version">等待规划</span>
      </div>
      <p className="lead">平台将基于 Case 事实匹配 Policy、Skill 与 Knowledge，枚举可探索路径；Agent 只提出方案，不会修改业务系统。</p>
      <article className="pathCard compactPath">
        <div className="pathHeading"><span className="pathBadge">CASE READY</span></div>
        <h3>订单延期 · SO-48392</h3>
        <p>关键物料 MCU-X7 存在 18,400 pcs 缺口，目标交付日为 2026-08-24。</p>
      </article>
      <div className="approvalBox">
        <span><strong>下一步：生成可审查的 Manifest</strong><small>Planner 无权发明 Path、删除强制责任或作出业务承诺。</small></span>
        <button className="primary" disabled={busy} onClick={generateManifest}>{busy ? "组装中…" : "生成 Manifest"}</button>
      </div>
    </>
  ) : (
    <>
      <div className="panelTitle">
        <div><span className="agentIcon">✦</span><span><small>ORCHESTRATOR 建议</small><h2>审查 Path Manifest</h2></span></div>
        <span className="version">v1 · 待批准</span>
      </div>
      <p className="lead">命中的缺料处理 Skill 支持以下三条 Path。Owner 可以选择本轮真正进入探索的 Path。</p>
      <div className="pathChoices">
        {manifestPaths.map((path, index) => {
          const snapshot = capabilitySnapshots[path.id];
          const selected = selectedPathIds.includes(path.id);
          const commitments = snapshot?.compiled_policy.commitments ?? [];
          return (
            <article className={`pathCard ${selected ? "selected" : ""}`} key={path.id}>
              <div className="pathHeading">
                <span className="pathBadge">PATH {String(index + 1).padStart(2, "0")}</span>
                {path.definition === "MaterialSubstitution" && <span className="recommended">DEMO</span>}
                <label className="pathSelector">
                  <input type="checkbox" checked={selected} onChange={() => togglePath(path.id)} />
                  <span>{selected ? "本轮探索" : "暂不探索"}</span>
                </label>
              </div>
              <h3>{path.title} <span>{path.definition}</span></h3>
              <p>{path.rationale}</p>
              <div className="pathStats">
                <span><small>责任节点</small><strong>{commitments.length}</strong></span>
                <span><small>并行起点</small><strong>{commitments.filter((item) => !(item.depends_on?.length)).length}</strong></span>
                <span><small>强制 Policy</small><strong>{snapshot?.policies.length ?? 0}</strong></span>
                <span><small>命中 Skill</small><strong>{snapshot?.skills.length ?? 0}</strong></span>
              </div>
            </article>
          );
        })}
      </div>
      <button className="linkButton capabilityToggle" onClick={toggleCapabilities}>{showCapabilities ? "收起替代 Path 能力快照 ↑" : "查看替代 Path 能力快照 →"}</button>
      {showCapabilities && capabilities && <CapabilityPanel details={capabilities} />}
      <div className="approvalBox">
        <span><strong>批准范围 · 已选 {selectedPathIds.length} 条</strong><small>只为勾选的 Path 创建 PathAttempt，不代表批准最终业务方案。</small></span>
        <button className="primary" disabled={busy || selectedPathIds.length === 0} onClick={approveManifest}>{busy ? "处理中…" : "批准并启动所选 Path"}</button>
      </div>
    </>
  );

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandMark">AC</span>
          <div><strong>Agentic CM</strong><small>Supply chain cases</small></div>
        </div>
        <nav aria-label="主要导航" className="nav">
          <a className="navItem active" href="#cases"><span>◇</span> Cases <b>5</b></a>
          <button className={`navItem ${showInbox ? "active" : ""}`} onClick={() => setShowInbox(true)}><span>□</span> 我的 Inbox <b>{inboxItems.length}</b></button>
          <a className="navItem" href="#assets"><span>◎</span> 组织资产</a>
        </nav>
        <div className="caseList" id="cases">
          <p className="sectionLabel">相关 Cases</p>
          {cases.map((item) => (
            <a className={`caseItem ${item.active ? "active" : ""}`} href={`#${item.id}`} key={item.id}>
              <span className="caseDot" />
              <span><strong>{item.title}</strong><small>{item.id} · {item.status}</small></span>
            </a>
          ))}
        </div>
        <div className="identity">
          <span className="avatar">{currentIdentity.avatar}</span>
          <span><small>当前角色</small><strong>{currentIdentity.name} · {currentIdentity.role}</strong></span>
          <button aria-label="切换演示身份" onClick={() => setIdentityIndex((current) => (current + 1) % demoIdentities.length)}>⌄</button>
          <em>Demo identity simulation</em>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">Cases <span>/</span> CM-2026-014</div>
          <div className="topActions"><button className="ghost">审计记录</button><button className="ghost" disabled={busy} onClick={resetDemo}>重置 Demo</button></div>
        </header>
        <div className="content">
          <header className="issueHeader">
            <div>
              <div className="eyebrow">SUPPLY CHAIN CASE <span>·</span> 高优先级</div>
              <h1>订单预计延期 <span>#CM-2026-014</span></h1>
              <p><span className="openBadge">● Open</span> 陈澄于今天 08:46 创建 · 当前由 <strong>陈澄</strong> 负责</p>
            </div>
            <button className="primary">继续处理 <span>→</span></button>
          </header>

          <div className="mainGrid threadLayout">
            <section className="caseThread" aria-label="Case 完整流转 Thread">
              {message && <div className="toast" role="status">{message}</div>}

              <article className="threadItem commentItem">
                <div className="threadAvatar humanAvatar">陈</div>
                <div className="commentBox">
                  <header><strong>陈澄</strong><span>Case Owner · 今天 08:46</span><b>创建 Case</b></header>
                  <div className="commentBody">
                    <p>订单 SO-48392 的关键物料预计晚于承诺日期 12 天，可能影响客户交付。</p>
                    <h3>Human Proposal</h3>
                    <blockquote>建议优先评估现有认证范围内的替代物料，避免直接承诺未经客户确认的新方案。</blockquote>
                    <div className="factChips"><span>MCU-X7</span><span>缺口 18,400 pcs</span><span>目标 2026-08-24</span></div>
                  </div>
                </div>
              </article>

              <div className="threadEvent completedEvent">
                <span className="eventIcon">✓</span>
                <p><strong>平台完成 Case 受理</strong><span>事实已固化，责任人为陈澄 · 今天 08:47</span></p>
              </div>

              {phase !== "INTAKE" && (
                <div className="threadEvent completedEvent">
                  <span className="eventIcon botEvent">✦</span>
                  <p><strong>Orchestrator 生成 Manifest v1</strong><span>匹配组织能力并冻结 Policy / Skill / Knowledge 快照 · 今天 09:02</span></p>
                </div>
              )}

              {approved && (
                <div className="threadEvent completedEvent">
                  <span className="eventIcon humanEvent">陈</span>
                  <p><strong>陈澄批准 Manifest</strong><span>启动物料替代 PathAttempt，最终业务决定尚未作出 · 今天 09:18</span></p>
                </div>
              )}

              <article className="threadItem commentItem currentThreadItem">
                <div className="threadAvatar botAvatar">AC</div>
                <div className="commentBox activeComment">
                  <header><strong>Agentic CM</strong><span>Orchestrator · 当前步骤</span><b className="currentLabel">{currentStage}</b></header>
                  <div className="commentBody actionBody">{orchestrationCard}</div>
                </div>
              </article>

              <div className="futureFlow" aria-label="后续流程">
                <div><span>4</span><p><strong>专业承诺汇合</strong><small>供应与技术并行评审；依赖未满足时下游保持阻塞</small></p></div>
                <div><span>5</span><p><strong>Case Owner 最终决策</strong><small>基于已承诺证据选择、修订或拒绝方案</small></p></div>
                <div><span>6</span><p><strong>受控行动与结果验证</strong><small>执行结果回写 Case；未解决则开启新一轮，解决后关闭</small></p></div>
              </div>
            </section>

            <aside className="rightRail">
              <section className="panel flowSummary">
                <div className="compactTitle"><h2>完整流程</h2><span>{activeStageIndex + 1} / {stages.length}</span></div>
                <ol>
                  {stages.map((stage, index) => (
                    <li className={index < activeStageIndex ? "complete" : index === activeStageIndex ? "current" : ""} key={stage}>
                      <span>{index < activeStageIndex ? "✓" : index + 1}</span>
                      <div><strong>{stage}</strong><small>{index === activeStageIndex ? "进行中" : index < activeStageIndex ? "已完成" : "尚未开始"}</small></div>
                    </li>
                  ))}
                </ol>
              </section>
              <section className="panel facts">
                <div className="compactTitle"><h2>Case 事实</h2><button>查看全部</button></div>
                <dl>
                  <div><dt>Case Owner</dt><dd>陈澄</dd></div>
                  <div><dt>订单</dt><dd>SO-48392</dd></div>
                  <div><dt>客户</dt><dd>Northstar Mobility</dd></div>
                  <div><dt>关键物料</dt><dd>MCU-X7</dd></div>
                  <div><dt>缺口数量</dt><dd>18,400 pcs</dd></div>
                  <div><dt>目标交付日</dt><dd>2026-08-24</dd></div>
                </dl>
              </section>
              <section className="notice"><strong>演示安全边界</strong><p>不连接或修改 ERP、库存、订单及客户系统；所有执行均为 sandbox 推演。</p></section>
            </aside>
          </div>
        </div>
      </section>

      {showInbox && (
        <div className="inboxBackdrop" role="presentation">
          <aside className="inboxDrawer" aria-label={`${currentIdentity.role} Inbox`}>
            <header>
              <div><small>ROLE INBOX</small><h2>{currentIdentity.role}</h2><p>{currentIdentity.name} · Demo identity simulation</p></div>
              <button aria-label="关闭 Inbox" onClick={() => setShowInbox(false)}>×</button>
            </header>
            <div className="inboxHint">这里只显示分配给当前角色、且依赖已经满足的待批准节点。请从左下角切换演示身份。</div>
            <div className="inboxList">
              {inboxItems.length ? inboxItems.map((node) => (
                <article key={`${node.path_id}-${node.id}`}>
                  <div><span>PENDING</span><small>{node.path_id} · {node.id}</small></div>
                  <h3>{commitmentCopy[node.id] ?? node.role}</h3>
                  <p>Case CM-2026-014 · {manifestPaths.find((path) => path.id === node.path_id)?.title ?? node.path_id}</p>
                  <button className="primary" disabled={busy} onClick={() => approveCommitment(node)}>{busy ? "处理中…" : "批准并设为 READY"}</button>
                </article>
              )) : (
                <div className="emptyInbox"><strong>当前没有待批准事项</strong><p>如果 Manifest 已批准，请切换到主计划或研发身份查看各自任务。</p></div>
              )}
            </div>
          </aside>
        </div>
      )}
    </main>
  );
}
