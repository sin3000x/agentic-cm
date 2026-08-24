"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import AppSidebar from "../../app-sidebar";
import "./case-detail.css";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? `http://localhost:${process.env.AGENTIC_CM_API_PORT ?? 8000}`;

const stages = ["Case 受理", "Manifest 评审", "Path 探索", "专业承诺", "最终决策", "结果验证"];

const demoIdentities = [
  { name: "陈澄", role: "订单统筹经理", avatar: "陈" },
  { name: "王淼", role: "主计划", avatar: "王" },
  { name: "林乔", role: "研发", avatar: "林" },
  { name: "赵宁", role: "供应经理", avatar: "赵" },
];

const commitmentCopy: Record<string, string> = {
  SUPPLY: "确认 Manifest 候选物料的供应可行性",
  TECH: "确认 Manifest 候选物料的技术可行性",
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
  status: "BLOCKED" | "PENDING" | "READY" | "COMMITTED" | "STALE" | "REJECTED";
  depends_on: string[];
  path_id: string;
};

type CommitmentDecision = "APPROVE" | "REVISE" | "REJECT";

type SolutionOption = {
  id: string;
  title: string;
  description: string;
  benefits: string[];
  risks: string[];
  assumptions: string[];
};

type SolutionRevision = {
  revision: number;
  path_id: string;
  path_definition: string;
  summary: string;
  options: SolutionOption[];
  recommendation: { option_ids: string[]; rationale: string };
  evidence_gaps: string[];
  role_reports: Array<{ role: string; dimension: string; report: string }>;
  required_commitment_ids: string[];
  generated_by: string;
  manifest_ref: { id: string; revision: number };
};

type PathAttempt = {
  id: string;
  path_id: string;
  definition: string;
  phase: string;
  solution_revision: SolutionRevision | null;
};

function isSolutionRevision(value: unknown): value is SolutionRevision {
  if (!value || typeof value !== "object") return false;
  const revision = value as Partial<SolutionRevision>;
  return Array.isArray(revision.options)
    && revision.options.every((option) => option
      && typeof option === "object"
      && Array.isArray(option.benefits)
      && Array.isArray(option.risks)
      && Array.isArray(option.assumptions))
    && !!revision.recommendation
    && Array.isArray(revision.recommendation.option_ids)
    && Array.isArray(revision.evidence_gaps)
    && Array.isArray(revision.role_reports)
    && revision.role_reports.every((item) => item
      && typeof item.role === "string"
      && typeof item.dimension === "string"
      && typeof item.report === "string");
}

type InboxItem = {
  case_id: string;
  case_title: string;
  path_id: string;
  path_title: string;
  node: CommitmentNode;
};

type TimelineEvent = {
  id: number;
  event_type: "manifest.proposed" | "manifest.approved" | "solution_revision.proposed" | "commitment.approved" | "commitment.revision_requested" | "commitment.rejected";
  created_at: string;
  details: {
    revision?: number;
    actor?: string;
    role?: string;
    node_id?: string;
    path_id?: string;
    option_count?: number;
  };
};

type AgentTraceEvent = {
  id: number;
  sequence: number;
  step: string;
  status: "STARTED" | "COMPLETED" | "FAILED";
  summary: string;
  details: Record<string, unknown>;
  created_at: string;
};

type AgentRun = {
  id: string;
  agent_type: "orchestrator" | "path" | "synthesis";
  status: "RUNNING" | "SUCCEEDED" | "FAILED";
  adapter_profile: string;
  initiated_by: string;
  started_at: string;
  completed_at: string | null;
  error_type: string | null;
  error_message: string | null;
  events: AgentTraceEvent[];
};

const threadTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function formatThreadTime(value: string | null) {
  return value ? threadTimeFormatter.format(new Date(value)) : "时间读取中";
}

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

function AgentTracePanel({ runs, agentType }: { runs: AgentRun[]; agentType: "orchestrator" | "path" }) {
  const label = agentType === "orchestrator" ? "ORCHESTRATOR" : "PATH AGENT";
  const typedRuns = runs.filter((run) => run.agent_type === agentType);
  return (
    <section className="agentTracePanel" aria-label={`${label} Trace`}>
      <div className="traceHeader">
        <span><strong>{label} TRACE</strong><small>可审计步骤；不记录 API Key 或隐藏思维链</small></span>
        <em>{typedRuns.length} RUNS</em>
      </div>
      {typedRuns.length === 0 ? (
        <p className="emptyTrace">尚无 {label} 运行记录。</p>
      ) : typedRuns.map((run) => (
        <details className={`traceRun ${run.status.toLowerCase()}`} key={run.id}>
          <summary>
            <span><b>{run.status}</b><strong>{run.adapter_profile}</strong></span>
            <small>{formatThreadTime(run.started_at)} · {run.events.length} steps</small>
          </summary>
          {run.error_message && <p className="traceError">{run.error_type}: {run.error_message}</p>}
          <ol className="traceSteps">
            {run.events.map((event) => (
              <li className={event.status.toLowerCase()} key={event.id}>
                <span className="traceSequence">{String(event.sequence).padStart(2, "0")}</span>
                <div>
                  <header><code>{event.step}</code><b>{event.status}</b><time>{formatThreadTime(event.created_at)}</time></header>
                  <p>{event.summary}</p>
                  {Object.keys(event.details).length > 0 && (
                    <details className="tracePayload">
                      <summary>查看输入 / 输出详情</summary>
                      <pre>{JSON.stringify(event.details, null, 2)}</pre>
                    </details>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </details>
      ))}
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
  const [pathAttempts, setPathAttempts] = useState<PathAttempt[]>([]);
  const [timelineEvents, setTimelineEvents] = useState<TimelineEvent[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([]);
  const [pathAgentRuns, setPathAgentRuns] = useState<AgentRun[]>([]);
  const [showOrchestratorTrace, setShowOrchestratorTrace] = useState(false);
  const [expandedPathTraces, setExpandedPathTraces] = useState<Record<string, boolean>>({});
  const [caseCreatedAt, setCaseCreatedAt] = useState<string | null>(null);
  const [canViewManifest, setCanViewManifest] = useState(true);
  const [identityIndex, setIdentityIndex] = useState(0);
  const identityIndexRef = useRef(0);
  const [showInbox, setShowInbox] = useState(false);
  const [inboxItems, setInboxItems] = useState<InboxItem[]>([]);
  const currentIdentity = demoIdentities[identityIndex];

  function selectIdentity(nextIdentityIndex: number) {
    identityIndexRef.current = nextIdentityIndex;
    setCanViewManifest(false);
    setManifestPaths([]);
    setCapabilitySnapshots({});
    setSelectedPathIds([]);
    setCapabilities(null);
    setShowCapabilities(false);
    setAgentRuns([]);
    setPathAgentRuns([]);
    setShowOrchestratorTrace(false);
    setExpandedPathTraces({});
    setInboxItems([]);
    setIdentityIndex(nextIdentityIndex);
  }

  function loadManifest(manifest: { paths?: ManifestPath[]; capability_snapshots?: Record<string, CapabilitySnapshot> } | null) {
    const paths = manifest?.paths ?? [];
    setManifestPaths(paths);
    setCapabilitySnapshots(manifest?.capability_snapshots ?? {});
    const substitution = paths.find((path) => path.definition === "MaterialSubstitution");
    setSelectedPathIds(substitution ? [substitution.id] : paths.slice(0, 1).map((path) => path.id));
  }

  useEffect(() => {
    const identity = demoIdentities[identityIndex];
    const query = new URLSearchParams({ actor: identity.name, role: identity.role });
    const controller = new AbortController();
    Promise.all([
      fetch(`${API_BASE}/api/cases/CM-2026-014?${query}`, { signal: controller.signal }),
      fetch(`${API_BASE}/api/cases/CM-2026-014/timeline`, { signal: controller.signal }),
      fetch(`${API_BASE}/api/inbox?${new URLSearchParams({ role: identity.role })}`, { signal: controller.signal }),
    ])
      .then(([caseResponse, timelineResponse, inboxResponse]) => {
        if (!caseResponse.ok || !timelineResponse.ok || !inboxResponse.ok) return Promise.reject();
        return Promise.all([caseResponse.json(), timelineResponse.json(), inboxResponse.json()]);
      })
      .then(([data, timeline, inbox]) => {
        setPhase(data.phase);
        setApproved(data.phase === "PATH_EXPLORATION");
        setCommitmentNodes(data.commitment_nodes ?? []);
        setPathAttempts(data.path_attempts ?? []);
        setTimelineEvents(timeline);
        setInboxItems(inbox);
        setCaseCreatedAt(data.created_at);
        setCanViewManifest(data.permissions?.can_view_manifest === true);
        loadManifest(data.manifest);
        if (data.phase === "PATH_EXPLORATION") {
          setSelectedPathIds((data.manifest?.paths ?? []).filter((path: ManifestPath) => path.selected).map((path: ManifestPath) => path.id));
        }
        if (data.permissions?.can_view_manifest === true) {
          const traceQuery = new URLSearchParams({
            actor: identity.name,
            role: identity.role,
          });
          Promise.all(["orchestrator", "path"].map((agentType) => {
            const query = new URLSearchParams(traceQuery);
            query.set("agent_type", agentType);
            return fetch(`${API_BASE}/api/cases/CM-2026-014/agent-runs?${query}`, { signal: controller.signal })
              .then((response) => response.ok ? response.json() : []);
          }))
            .then(([orchestratorRuns, loadedPathRuns]) => {
              setAgentRuns(orchestratorRuns);
              setPathAgentRuns(loadedPathRuns);
            })
            .catch((error) => {
              if (!(error instanceof DOMException && error.name === "AbortError")) {
                setAgentRuns([]);
                setPathAgentRuns([]);
              }
            });
        }
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setMessage("API 尚未连接，当前展示固定演示数据。");
      });
    return () => controller.abort();
  }, [identityIndex]);

  async function refreshTimeline() {
    try {
      const response = await fetch(`${API_BASE}/api/cases/CM-2026-014/timeline`);
      if (response.ok) setTimelineEvents(await response.json());
    } catch {
      // The business action has already succeeded; the next Case refresh will reload the Thread.
    }
  }

  async function refreshInbox() {
    try {
      const query = new URLSearchParams({ role: currentIdentity.role });
      const response = await fetch(`${API_BASE}/api/inbox?${query}`);
      if (response.ok) setInboxItems(await response.json());
    } catch {
      // Inbox can be refreshed independently without changing the Case decision.
    }
  }

  async function refreshAgentRuns() {
    if (!canViewManifest) return;
    try {
      const baseQuery = { actor: currentIdentity.name, role: currentIdentity.role };
      const [orchestratorResponse, pathResponse] = await Promise.all([
        fetch(`${API_BASE}/api/cases/CM-2026-014/agent-runs?${new URLSearchParams({ ...baseQuery, agent_type: "orchestrator" })}`),
        fetch(`${API_BASE}/api/cases/CM-2026-014/agent-runs?${new URLSearchParams({ ...baseQuery, agent_type: "path" })}`),
      ]);
      if (orchestratorResponse.ok) setAgentRuns(await orchestratorResponse.json());
      if (pathResponse.ok) setPathAgentRuns(await pathResponse.json());
    } catch {
      // Trace persistence is independent from the business action and can be reloaded later.
    }
  }

  async function generateManifest() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/cases/CM-2026-014/orchestrate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: currentIdentity.name, role: currentIdentity.role }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail ?? "orchestrate failed");
      }
      const data = await response.json();
      setPhase("MANIFEST_REVIEW");
      loadManifest(data.manifest);
      setCapabilities(null);
      await refreshTimeline();
      setMessage("Orchestrator 已根据 Case 与现有能力生成 Manifest，并冻结适用 Policy。 ");
    } catch (error) {
      setMessage(`Manifest 生成失败：${error instanceof Error ? error.message : "请确认本地 API 与 Planner 配置"}。`);
    } finally {
      await refreshAgentRuns();
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
        body: JSON.stringify({
          selected_path_ids: selectedPathIds,
          actor: currentIdentity.name,
          role: currentIdentity.role,
        }),
      });
      if (!response.ok) throw new Error("approve failed");
      const data = await response.json();
      setManifestPaths(data.manifest.paths);
      setCommitmentNodes(data.commitment_nodes ?? []);
      setPathAttempts(data.path_attempts ?? []);
      setApproved(true);
      setPhase("PATH_EXPLORATION");
      await refreshTimeline();
      setMessage("Manifest 已批准；主计划与研发任务已分别投递到各自 Inbox，等待本人批准。 ");
    } catch {
      setMessage("无法连接本地 API，请先启动 Python 服务。 ");
    } finally {
      setBusy(false);
    }
  }

  async function generateAlternatives(pathId: string) {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/cases/CM-2026-014/paths/${pathId}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: currentIdentity.name, role: currentIdentity.role }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail ?? "Path Agent failed");
      }
      const data = await response.json();
      setPathAttempts(data.path_attempts ?? []);
      await refreshTimeline();
      setMessage("Path Agent 已从冻结 Manifest 组装并生成可审查的替代方案。 ");
    } catch (error) {
      setMessage(`替代方案生成失败：${error instanceof Error ? error.message : "请确认 Path Agent 配置"}。`);
    } finally {
      await refreshAgentRuns();
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
      setPathAttempts([]);
      setTimelineEvents([]);
      setAgentRuns([]);
      setPathAgentRuns([]);
      setShowOrchestratorTrace(false);
      setExpandedPathTraces({});
      setCaseCreatedAt(new Date().toISOString());
      setCanViewManifest(true);
      identityIndexRef.current = 0;
      setIdentityIndex(0);
      setShowInbox(false);
      setInboxItems([]);
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
      const requestIdentityIndex = identityIndex;
      const query = new URLSearchParams({ actor: currentIdentity.name, role: currentIdentity.role });
      const response = await fetch(`${API_BASE}/api/cases/CM-2026-014/capabilities?${query}`);
      if (!response.ok) throw new Error("capabilities failed");
      const data = await response.json();
      if (identityIndexRef.current !== requestIdentityIndex) return;
      setCapabilities(data);
    } catch {
      setShowCapabilities(false);
      setMessage("能力快照读取失败：请确认本地 API 已启动。 ");
    }
  }

  async function decideCommitment(caseId: string, node: CommitmentNode, decision: CommitmentDecision) {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(
        `${API_BASE}/api/cases/${caseId}/paths/${node.path_id}/commitments/${node.id}/decision`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ actor: currentIdentity.name, role: currentIdentity.role, decision }),
        },
      );
      if (!response.ok) throw new Error("commitment decision failed");
      const data = await response.json();
      if (caseId === "CM-2026-014") {
        setCommitmentNodes(data.commitment_nodes ?? []);
        await refreshTimeline();
      }
      await refreshInbox();
      const result = decision === "APPROVE" ? "通过" : decision === "REVISE" ? "要求修改" : "否决";
      setMessage(`${currentIdentity.name} 已${result} ${caseId} 的 ${node.id} 节点。`);
    } catch {
      setMessage("审批操作失败：请确认当前身份、节点状态与本地 API。 ");
    } finally {
      setBusy(false);
    }
  }

  const activeStageIndex = approved ? 2 : phase === "INTAKE" ? 0 : 1;
  const currentStage = stages[activeStageIndex];
  const selectedAttemptPathId = manifestPaths.find((path) => path.selected)?.id
    ?? selectedPathIds[0]
    ?? commitmentNodes[0]?.path_id;
  const activeCommitments = commitmentNodes.filter((node) => node.path_id === selectedAttemptPathId);
  const activePathAttempt = pathAttempts.find((attempt) => attempt.path_id === selectedAttemptPathId);
  const solutionRevision = isSolutionRevision(activePathAttempt?.solution_revision)
    ? activePathAttempt.solution_revision
    : null;
  const activePathAgentRuns = solutionRevision
    ? pathAgentRuns.filter((run) => run.agent_type === "path" && run.events.some(
      (event) => event.step === "run.started" && event.details.path_id === solutionRevision.path_id,
    ))
    : [];

  function approvalActions(caseId: string, node: CommitmentNode) {
    if (node.status !== "PENDING" || node.role !== currentIdentity.role) return null;
    return (
      <div className="approvalActions" aria-label={`${node.id} 审批操作`}>
        <button className="decisionApprove" disabled={busy} onClick={() => decideCommitment(caseId, node, "APPROVE")}>通过</button>
        <button className="decisionRevise" disabled={busy} onClick={() => decideCommitment(caseId, node, "REVISE")}>修改</button>
        <button className="decisionReject" disabled={busy} onClick={() => decideCommitment(caseId, node, "REJECT")}>否决</button>
      </div>
    );
  }

  function commitmentNode(nodeId: string, fallbackRole: string, fallbackStatus: CommitmentNode["status"]) {
    const node = activeCommitments.find((item) => item.id === nodeId) ?? {
      id: nodeId,
      role: fallbackRole,
      node_type: "APPROVAL",
      status: fallbackStatus,
      depends_on: nodeId === "CUSTOMER" ? ["SUPPLY", "TECH"] : [],
      path_id: selectedAttemptPathId ?? "PATH-01",
    };
    const statusLabel = node.status === "PENDING"
      ? node.role === currentIdentity.role ? "待本人批准" : `待${node.role}批准`
      : node.status === "BLOCKED" ? "等待前置审批"
      : node.status === "READY" ? "已通过"
      : node.status === "STALE" ? "待方案修改"
      : node.status === "REJECTED" ? "已否决"
      : node.status;
    return (
      <article className={`dagNode ${node.depends_on.length ? "downstream" : "upstream"} ${node.status.toLowerCase()}`}>
        <span>{statusLabel}</span>
        <h3>{node.role}</h3>
        <p>{commitmentCopy[node.id] ?? "等待责任人确认"}</p>
        {approvalActions("CM-2026-014", node)}
      </article>
    );
  }

  const orchestrationCard = phase === "MANIFEST_REVIEW" && !canViewManifest ? (
    <>
      <div className="panelTitle">
        <div><span className="agentIcon">⌁</span><span><small>OWNER-ONLY REVIEW</small><h2>Manifest 正在等待 Case Owner 审批</h2></span></div>
        <span className="version">内容已隐藏</span>
      </div>
      <p className="lead">Manifest 的 Path、理由、Policy、Skill 和能力快照仅 Case Owner 可见。当前身份不能查看内容，也不能执行审批。</p>
      <article className="pathCard compactPath">
        <div className="pathHeading"><span className="pathBadge">ACCESS RESTRICTED</span></div>
        <h3>等待陈澄完成评审</h3>
        <p>审批完成后，平台只会向相关角色的 Inbox 投递其本人需要处理的责任节点。</p>
      </article>
    </>
  ) : approved ? (
    <>
      <div className="panelTitle">
        <div><span className="agentIcon">✓</span><span><small>PATH ATTEMPT · ATTEMPT-01</small><h2>物料替代 · 审批 DAG</h2></span></div>
        <span className="version">AWAITING INBOX</span>
      </div>
      <p className="lead">Path Agent 只使用已批准 Manifest 冻结的 Skill、Policy、Knowledge 与 Case 快照生成替代方案；主计划与研发仍需在各自 Inbox 作出独立确认。</p>
      {solutionRevision ? (
        <section className="solutionRevision" aria-label="Path Agent 替代方案">
          <div className="solutionHeader">
            <span><small>SOLUTION REVISION</small><strong>v{solutionRevision.revision} · {solutionRevision.path_definition}</strong></span>
            <em>{solutionRevision.generated_by}</em>
          </div>
          <p>{solutionRevision.summary}</p>
          <div className="solutionOptions">
            {solutionRevision.options.map((option) => (
              <article key={option.id}>
                <span>{option.id}</span>
                <h3>{option.title}</h3>
                <p>{option.description}</p>
                <dl>
                  <div><dt>收益</dt><dd>{option.benefits.join("；") || "待分析"}</dd></div>
                  <div><dt>风险</dt><dd>{option.risks.join("；") || "待分析"}</dd></div>
                  <div><dt>假设</dt><dd>{option.assumptions.join("；") || "无"}</dd></div>
                </dl>
              </article>
            ))}
          </div>
          <div className="solutionRecommendation">
            <strong>Agent 建议（非业务决定）</strong>
            <p>{solutionRevision.recommendation.rationale}</p>
            <small>证据缺口：{solutionRevision.evidence_gaps.join("；") || "无"}</small>
          </div>
          <div className="roleReports" aria-label="三个角色的替代判断报告">
            {solutionRevision.role_reports.map((item) => (
              <article key={`${item.role}-${item.dimension}`}>
                <span>{item.role}</span>
                <strong>{item.dimension}</strong>
                <p>{item.report}</p>
              </article>
            ))}
          </div>
          {activePathAgentRuns.length > 0 && (
            <>
              <button
                className="linkButton traceToggle"
                onClick={() => setExpandedPathTraces((current) => ({
                  ...current,
                  [solutionRevision.path_id]: !current[solutionRevision.path_id],
                }))}
              >
                {expandedPathTraces[solutionRevision.path_id]
                  ? "收起当前 Path Trace ↑"
                  : `查看当前 Path Trace (${activePathAgentRuns.length}) →`}
              </button>
              {expandedPathTraces[solutionRevision.path_id] && (
                <AgentTracePanel runs={activePathAgentRuns} agentType="path" />
              )}
            </>
          )}
          {activePathAttempt?.phase === "REVISING" && (
            <button className="linkButton" disabled={busy} onClick={() => generateAlternatives(solutionRevision.path_id)}>根据人类修改要求生成修订版 →</button>
          )}
        </section>
      ) : (
        <div className="approvalBox pathAgentLaunch">
          <span><strong>下一步：组装并运行 Path Agent</strong><small>从 Manifest 冻结快照加载 execution Skill 与强制 Policy；失败不会修改 Case。</small></span>
          <button className="primary" disabled={busy || !selectedAttemptPathId} onClick={() => selectedAttemptPathId && generateAlternatives(selectedAttemptPathId)}>{busy ? "生成中…" : "生成替代方案"}</button>
        </div>
      )}
      <div className="dag" aria-label="Commitment DAG">
        {commitmentNode("SUPPLY", "主计划", "PENDING")}
        {commitmentNode("TECH", "研发", "PENDING")}
        <div className="dagJoin"><i /><i /></div>
        {commitmentNode("CUSTOMER", "供应经理", "BLOCKED")}
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
      <AppSidebar
        active={showInbox ? "inbox" : "workspace"}
        identity={currentIdentity}
        identities={demoIdentities}
        inboxCount={inboxItems.length}
        busy={busy}
        onInboxOpen={() => setShowInbox(true)}
        onIdentitySelect={selectIdentity}
      />

      <section className="workspace">
        <header className="topbar">
          <div className="breadcrumbs"><Link href="/">Case 总览</Link> <span>/</span> CM-2026-014</div>
          <div className="topActions"><button className="ghost">审计记录</button><button className="ghost" disabled={busy} onClick={resetDemo}>重置 Demo</button></div>
        </header>
        <div className="content">
          <header className="issueHeader">
            <div>
              <div className="eyebrow">SUPPLY CHAIN CASE <span>·</span> 高优先级</div>
              <h1>Northstar MCU-X7 订单预计延期 12 天 <span>#CM-2026-014</span></h1>
              <p><span className="openBadge">● Open</span> 陈澄于 {formatThreadTime(caseCreatedAt)} 创建 · 当前由 <strong>陈澄</strong> 负责</p>
            </div>
            <button className="primary">继续处理 <span>→</span></button>
          </header>

          <div className="mainGrid threadLayout">
            <section className="caseThread" aria-label="Case 完整流转 Thread">
              {message && <div className="toast" role="status">{message}</div>}

              <article className="threadItem commentItem">
                <div className="threadAvatar humanAvatar">陈</div>
                <div className="commentBox">
                  <header><strong>陈澄</strong><span>Case Owner · {formatThreadTime(caseCreatedAt)}</span><b>创建 Case</b></header>
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
                <p><strong>平台完成 Case 受理</strong><span>事实已固化，责任人为陈澄 · {formatThreadTime(caseCreatedAt)}</span></p>
              </div>

              {timelineEvents.map((event) => {
                if (event.event_type === "manifest.proposed") {
                  return (
                    <div className="threadEvent completedEvent" key={event.id}>
                      <span className="eventIcon botEvent">✦</span>
                      <p><strong>Orchestrator 生成 Manifest v{event.details.revision ?? 1}</strong><span>匹配组织能力并冻结 Policy / Skill / Knowledge 快照 · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                if (event.event_type === "manifest.approved") {
                  return (
                    <div className="threadEvent completedEvent" key={event.id}>
                      <span className="eventIcon humanEvent">{event.details.actor?.slice(0, 1) ?? "人"}</span>
                      <p><strong>{event.details.actor ?? "Case Owner"} 批准 Manifest</strong><span>启动已批准的 PathAttempt，最终业务决定尚未作出 · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                if (event.event_type === "solution_revision.proposed") {
                  return (
                    <div className="threadEvent completedEvent" key={event.id}>
                      <span className="eventIcon botEvent">◇</span>
                      <p><strong>Path Agent 生成 SolutionRevision v{event.details.revision ?? 1}</strong><span>{event.details.path_id} · {event.details.option_count ?? 0} 个可审查选项；未作出业务承诺 · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                if (event.event_type === "commitment.approved") {
                  return (
                    <div className="threadEvent completedEvent" key={event.id}>
                      <span className="eventIcon humanEvent">{event.details.actor?.slice(0, 1) ?? "人"}</span>
                      <p><strong>{event.details.actor}（{event.details.role}）批准 {event.details.node_id}</strong><span>{commitmentCopy[event.details.node_id ?? ""] ?? "专业责任节点"}已确认，节点变为 READY · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                if (event.event_type === "commitment.revision_requested" || event.event_type === "commitment.rejected") {
                  const isRevision = event.event_type === "commitment.revision_requested";
                  return (
                    <div className="threadEvent" key={event.id}>
                      <span className="eventIcon humanEvent">{event.details.actor?.slice(0, 1) ?? "人"}</span>
                      <p><strong>{event.details.actor}（{event.details.role}）{isRevision ? "要求修改" : "否决"} {event.details.node_id}</strong><span>{isRevision ? "PathAttempt 进入 REVISING" : "当前 PathAttempt 已结束"} · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                return null;
              })}

              <article className="threadItem commentItem currentThreadItem">
                <div className="threadAvatar botAvatar">AC</div>
                <div className="commentBox activeComment">
                  <header><strong>Agentic CM</strong><span>{approved ? "Path Agent" : "Orchestrator"} · 当前步骤</span><b className="currentLabel">{currentStage}</b></header>
                  <div className="commentBody actionBody">
                    {orchestrationCard}
                    {canViewManifest && phase === "MANIFEST_REVIEW" && agentRuns.some((run) => run.agent_type === "orchestrator") && (
                      <>
                        <button className="linkButton traceToggle" onClick={() => setShowOrchestratorTrace((current) => !current)}>
                          {showOrchestratorTrace ? "收起 Orchestrator Trace ↑" : `查看 Orchestrator Trace (${agentRuns.filter((run) => run.agent_type === "orchestrator").length}) →`}
                        </button>
                        {showOrchestratorTrace && (
                          <AgentTracePanel runs={agentRuns} agentType="orchestrator" />
                        )}
                      </>
                    )}
                  </div>
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
            <div className="inboxHint">汇总所有 Case 中分配给当前角色、且依赖已经满足的待审批节点。请从左下角切换演示身份。</div>
            <div className="inboxList">
              {inboxItems.length ? inboxItems.map((item) => (
                <article key={`${item.case_id}-${item.path_id}-${item.node.id}`}>
                  <div><span>PENDING</span><small>{item.path_id} · {item.node.id}</small></div>
                  <h3>{commitmentCopy[item.node.id] ?? item.node.role}</h3>
                  <p>Case {item.case_id} · {item.case_title} · {item.path_title}</p>
                  {approvalActions(item.case_id, item.node)}
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
