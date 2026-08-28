"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import AppSidebar from "../../app-sidebar";
import { apiGet, apiGetText, apiPost, apiUrl, isAbort } from "../../lib/api";
import { demoIdentities } from "../../lib/identities";
import { formatQuantity, formatThreadTime } from "../../lib/format";
import {
  aiRunCopy,
  approvalContextFor,
  commitmentCopy,
  initialHumanProposal,
  isSolutionRevision,
  pathLabel,
  skillLabel,
  stages,
  type AgentRun,
  type ApprovalReview,
  type CapabilityDetails,
  type CaseDetails,
  type CaseManifest,
  type CasePhase,
  type CaseStatusValue,
  type CommitmentDecision,
  type CommitmentNode,
  type HumanProposal,
  type ManifestPath,
  type OwnerDecision,
  type PathAttempt,
  type PathExecutionMode,
  type PathExecutionResponse,
  type SolutionRevision,
  type SynthesisReport,
  type TimelineEvent,
  type AiRunKind,
} from "../../lib/case";
import { AgentTracePanel, AiWorkingCard, BotIcon, CapabilityPanel, ManifestYamlPanel, PersonIcon } from "./panels";
import "./case-detail.css";



export default function Home() {
  const params = useParams<{ id: string }>();
  const activeCaseId = params?.id ?? "";
  const [caseDetails, setCaseDetails] = useState<CaseDetails | null>(null);
  const [phase, setPhase] = useState<CasePhase>("INTAKE");
  const [caseStatus, setCaseStatus] = useState<CaseStatusValue>("OPEN");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [aiRunKind, setAiRunKind] = useState<AiRunKind | null>(null);
  const [aiRunStep, setAiRunStep] = useState(0);
  const [aiRunStartedAt, setAiRunStartedAt] = useState<string | null>(null);
  const [aiPathIds, setAiPathIds] = useState<string[]>([]);
  const [pathExecutionMode, setPathExecutionMode] = useState<PathExecutionMode>("parallel");
  const [pathMaxConcurrency, setPathMaxConcurrency] = useState(4);
  const [failedAiRun, setFailedAiRun] = useState<AiRunKind | null>(null);
  const [message, setMessage] = useState("");
  const [capabilities, setCapabilities] = useState<CapabilityDetails | null>(null);
  const [showCapabilities, setShowCapabilities] = useState(false);
  const [showManifestYaml, setShowManifestYaml] = useState(false);
  const [manifestYaml, setManifestYaml] = useState("");
  const [manifestPaths, setManifestPaths] = useState<ManifestPath[]>([]);
  const [manifestVersion, setManifestVersion] = useState<number | null>(null);
  const [showApprovedManifest, setShowApprovedManifest] = useState(false);
  const [selectedPathIds, setSelectedPathIds] = useState<string[]>([]);
  const [commitmentNodes, setCommitmentNodes] = useState<CommitmentNode[]>([]);
  const [pathAttempts, setPathAttempts] = useState<PathAttempt[]>([]);
  const [timelineEvents, setTimelineEvents] = useState<TimelineEvent[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([]);
  const [pathAgentRuns, setPathAgentRuns] = useState<AgentRun[]>([]);
  const [synthesisAgentRuns, setSynthesisAgentRuns] = useState<AgentRun[]>([]);
  const [synthesisReport, setSynthesisReport] = useState<SynthesisReport | null>(null);
  const [ownerDecision, setOwnerDecision] = useState<OwnerDecision | null>(null);
  const [humanProposal, setHumanProposal] = useState<HumanProposal>(initialHumanProposal);
  const [showModifyGuidance, setShowModifyGuidance] = useState(false);
  const [modifyGuidance, setModifyGuidance] = useState("");
  const [showSynthesisTrace, setShowSynthesisTrace] = useState(false);
  const [showOrchestratorTrace, setShowOrchestratorTrace] = useState(false);
  const [expandedPathTraces, setExpandedPathTraces] = useState<Record<string, boolean>>({});
  const [caseCreatedAt, setCaseCreatedAt] = useState<string | null>(null);
  const [canViewManifest, setCanViewManifest] = useState(true);
  const [identityIndex, setIdentityIndex] = useState(0);
  const [caseRefreshKey, setCaseRefreshKey] = useState(0);
  const identityIndexRef = useRef(0);
  const automaticRunsRef = useRef(new Set<string>());
  const [approvalReview, setApprovalReview] = useState<ApprovalReview | null>(null);
  const currentIdentity = demoIdentities[identityIndex];
  const startAutomaticManifest = useEffectEvent(() => { void generateManifest(); });
  const startAutomaticAlternatives = useEffectEvent((pathIds: string[]) => { void generateAlternatives(pathIds); });
  const startAutomaticSynthesis = useEffectEvent(() => { void generateSynthesis(); });
  const refreshLiveTrace = useEffectEvent(() => { void refreshAgentRuns(); });

  useEffect(() => {
    apiGet<{ path_execution_mode?: string; path_max_concurrency?: number }>("/api/runtime-config")
      .then((data) => {
        if (data.path_execution_mode === "parallel" || data.path_execution_mode === "serial") {
          setPathExecutionMode(data.path_execution_mode);
        }
        const concurrency = data.path_max_concurrency;
        if (Number.isInteger(concurrency) && concurrency !== undefined && concurrency > 0) {
          setPathMaxConcurrency(concurrency);
        }
      })
      .catch(() => {
        // The backend default is parallel; Case loading reports connection failures separately.
      });
  }, []);

  useEffect(() => {
    if (!aiRunKind) return;
    const timer = window.setInterval(() => {
      setAiRunStep((current) => Math.min(aiRunCopy[aiRunKind].steps.length - 1, current + 1));
    }, 1250);
    return () => window.clearInterval(timer);
  }, [aiRunKind]);

  useEffect(() => {
    if (!aiRunKind || !canViewManifest) return;
    refreshLiveTrace();
    const timer = window.setInterval(refreshLiveTrace, 600);
    return () => window.clearInterval(timer);
  }, [aiRunKind, canViewManifest]);

  function selectIdentity(nextIdentityIndex: number) {
    identityIndexRef.current = nextIdentityIndex;
    setCanViewManifest(false);
    setManifestPaths([]);
    setManifestVersion(null);
    setShowApprovedManifest(false);
    setSelectedPathIds([]);
    setCapabilities(null);
    setShowCapabilities(false);
    setShowManifestYaml(false);
    setManifestYaml("");
    setAgentRuns([]);
    setPathAgentRuns([]);
    setSynthesisAgentRuns([]);
    setSynthesisReport(null);
    setOwnerDecision(null);
    setShowSynthesisTrace(false);
    setShowModifyGuidance(false);
    setModifyGuidance("");
    setShowOrchestratorTrace(false);
    setExpandedPathTraces({});
    setApprovalReview(null);
    setIdentityIndex(nextIdentityIndex);
  }

  function loadManifest(
    manifest: CaseManifest | null | undefined,
    workflowPaths: ManifestPath[] = [],
  ) {
    const workflowById = new Map(workflowPaths.map((path) => [path.id, path]));
    const paths = (manifest?.paths ?? workflowPaths).map((path) => ({
      ...path,
      title: workflowById.get(path.id)?.title ?? path.title ?? path.definition,
      skill_selections: path.skill_selections ?? [],
    }));
    setManifestPaths(paths);
    setManifestVersion(manifest?.revision ?? null);
    const substitution = paths.find((path) => path.definition === "MaterialSubstitution");
    setSelectedPathIds(substitution ? [substitution.id] : paths.slice(0, 1).map((path) => path.id));
  }

  useEffect(() => {
    if (!activeCaseId) return;
    const identity = demoIdentities[identityIndex];
    const identityQuery = { actor: identity.name, role: identity.role };
    const controller = new AbortController();
    Promise.all([
      apiGet<CaseDetails>(`/api/cases/${activeCaseId}`, identityQuery, controller.signal),
      apiGet<TimelineEvent[]>(`/api/cases/${activeCaseId}/timeline`, undefined, controller.signal),
    ])
      .then(([data, timeline]) => {
        setCaseDetails(data);
        setPhase(data.phase);
        setCaseStatus(data.status);
        setApproved(["PATH_EXPLORATION", "PROFESSIONAL_COMMITMENT", "FINAL_REVIEW"].includes(data.phase));
        setCommitmentNodes(data.commitment_nodes ?? []);
        setPathAttempts(data.path_attempts ?? []);
        setSynthesisReport(data.synthesis_report ?? null);
        setOwnerDecision(data.owner_decision ?? null);
        setHumanProposal(data.human_proposal ?? initialHumanProposal);
        setTimelineEvents(timeline);
        setCaseCreatedAt(data.created_at);
        setCanViewManifest(data.permissions?.can_view_manifest === true);
        loadManifest(data.manifest, data.workflow_paths ?? []);
        if (["PATH_EXPLORATION", "PROFESSIONAL_COMMITMENT", "FINAL_REVIEW"].includes(data.phase)) {
          setSelectedPathIds((data.manifest?.paths ?? []).filter((path) => path.selected).map((path) => path.id));
        }
        if (data.permissions?.can_view_manifest === true) {
          Promise.all(["orchestrator", "path", "synthesis"].map((agentType) =>
            apiGet<AgentRun[]>(
              `/api/cases/${activeCaseId}/agent-runs`,
              { ...identityQuery, agent_type: agentType },
              controller.signal,
            ).catch(() => [] as AgentRun[])))
            .then(([orchestratorRuns, loadedPathRuns, loadedSynthesisRuns]) => {
              setAgentRuns(orchestratorRuns);
              setPathAgentRuns(loadedPathRuns);
              setSynthesisAgentRuns(loadedSynthesisRuns);
            })
            .catch((error) => {
              if (!(error instanceof DOMException && error.name === "AbortError")) {
                setAgentRuns([]);
                setPathAgentRuns([]);
                setSynthesisAgentRuns([]);
              }
            });
        }
        if (data.permissions?.can_view_manifest === true && data.phase === "INTAKE" && !data.manifest) {
          const runKey = `${identity.name}:manifest:${data.version ?? "current"}`;
          if (!automaticRunsRef.current.has(runKey)) {
            automaticRunsRef.current.add(runKey);
            startAutomaticManifest();
          }
        }
        if (data.permissions?.can_view_manifest === true && data.phase === "PATH_EXPLORATION") {
          const pendingPathIds = (data.manifest?.paths ?? [])
            .filter((path: ManifestPath) => path.selected)
            .filter((path: ManifestPath) => {
              const attempt = (data.path_attempts ?? []).find((item: PathAttempt) => item.path_id === path.id);
              return !attempt || attempt.state === "REVISING" || !isSolutionRevision(attempt.solution_revision);
            })
            .map((path: ManifestPath) => path.id);
          const runKey = `${identity.name}:alternatives:${pendingPathIds.join(",")}`;
          if (pendingPathIds.length > 0 && !automaticRunsRef.current.has(runKey)) {
            automaticRunsRef.current.add(runKey);
            startAutomaticAlternatives(pendingPathIds);
          }
        }
        if (data.permissions?.can_decide_case === true && data.phase === "FINAL_REVIEW" && !data.synthesis_report) {
          const runKey = `${identity.name}:synthesis:${data.version ?? "current"}`;
          if (!automaticRunsRef.current.has(runKey)) {
            automaticRunsRef.current.add(runKey);
            startAutomaticSynthesis();
          }
        }
      })
      .catch((error) => {
        if (isAbort(error)) return;
        setMessage("API 尚未连接，无法同步当前 Case 数据。");
      });
    return () => controller.abort();
  }, [activeCaseId, identityIndex, caseRefreshKey]);

  async function refreshTimeline() {
    try {
      setTimelineEvents(await apiGet<TimelineEvent[]>(`/api/cases/${activeCaseId}/timeline`));
    } catch {
      // The business action has already succeeded; the next Case refresh will reload the Thread.
    }
  }

  async function refreshAgentRuns() {
    if (!canViewManifest) return;
    try {
      const baseQuery = { actor: currentIdentity.name, role: currentIdentity.role };
      const loadRuns = (agentType: string) => apiGet<AgentRun[]>(
        `/api/cases/${activeCaseId}/agent-runs`,
        { ...baseQuery, agent_type: agentType },
      );
      const [orchestratorRuns, loadedPathRuns, loadedSynthesisRuns] = await Promise.all([
        loadRuns("orchestrator"), loadRuns("path"), loadRuns("synthesis"),
      ]);
      setAgentRuns(orchestratorRuns);
      setPathAgentRuns(loadedPathRuns);
      setSynthesisAgentRuns(loadedSynthesisRuns);
    } catch {
      // Trace persistence is independent from the business action and can be reloaded later.
    }
  }

  async function generateManifest() {
    setBusy(true);
    setAiRunStartedAt(new Date().toISOString());
    setAiRunKind("manifest");
    setAiRunStep(0);
    setFailedAiRun(null);
    setMessage("");
    try {
      const data = await apiPost<CaseDetails>(`/api/cases/${activeCaseId}/orchestrate`, { actor: currentIdentity.name, role: currentIdentity.role });
      setPhase("MANIFEST_REVIEW");
      loadManifest(data.manifest, data.workflow_paths ?? []);
      setCapabilities(null);
      setShowManifestYaml(false);
      setManifestYaml("");
      await refreshTimeline();
      setMessage("Orchestrator 已根据 Case 与现有能力生成 Manifest，并冻结适用 Policy。 ");
    } catch (error) {
      setFailedAiRun("manifest");
      setMessage(`Manifest 生成失败：${error instanceof Error ? error.message : "请确认本地 API 与 Planner 配置"}。`);
    } finally {
      await refreshAgentRuns();
      setAiRunKind(null);
      setBusy(false);
    }
  }

  async function approveManifest() {
    setBusy(true);
    setMessage("");
    try {
      const data = await apiPost<CaseDetails>(`/api/cases/${activeCaseId}/manifest/approve`, {
        selected_path_ids: selectedPathIds,
        actor: currentIdentity.name,
        role: currentIdentity.role,
      });
      loadManifest(data.manifest, data.workflow_paths ?? []);
      setSelectedPathIds((data.manifest?.paths ?? []).filter((path) => path.selected).map((path) => path.id));
      setCommitmentNodes(data.commitment_nodes ?? []);
      setPathAttempts(data.path_attempts ?? []);
      setApproved(true);
      setPhase("PATH_EXPLORATION");
      await refreshTimeline();
      const approvedPathIds = (data.manifest?.paths ?? [])
        .filter((path) => path.selected)
        .map((path) => path.id);
      setMessage("Manifest 已批准；Path Agent 将自动推演所选 Path。 ");
      await generateAlternatives(approvedPathIds);
    } catch {
      setMessage("无法连接本地 API，请先启动 Python 服务。 ");
    } finally {
      setBusy(false);
    }
  }

  async function generateAlternatives(pathIds: string | string[]) {
    const requestedPathIds = Array.isArray(pathIds) ? pathIds : [pathIds];
    if (requestedPathIds.length === 0) return;
    setBusy(true);
    setAiRunStartedAt(new Date().toISOString());
    setAiRunKind("alternatives");
    setAiRunStep(0);
    setAiPathIds(requestedPathIds);
    setFailedAiRun(null);
    setMessage("");
    try {
      const data = await apiPost<PathExecutionResponse>(`/api/cases/${activeCaseId}/paths/execute`, {
          path_ids: requestedPathIds,
          actor: currentIdentity.name,
          role: currentIdentity.role,
        });
      const updatedCase = data.case;
      if (data.execution_mode === "parallel" || data.execution_mode === "serial") {
        setPathExecutionMode(data.execution_mode);
      }
      if (Number.isInteger(data.max_concurrency) && data.max_concurrency > 0) {
        setPathMaxConcurrency(data.max_concurrency);
      }
      setPathAttempts(updatedCase.path_attempts ?? []);
      setCommitmentNodes(updatedCase.commitment_nodes ?? []);
      setPhase(updatedCase.phase);
      setApproved(["PATH_EXPLORATION", "PROFESSIONAL_COMMITMENT", "FINAL_REVIEW"].includes(updatedCase.phase));
      await refreshAgentRuns();
      await refreshTimeline();
      setMessage(`Path Agent 已${data.execution_mode === "parallel" ? "并行" : "逐条"}完成 ${requestedPathIds.length} 条 Path 的可审查替代方案。 `);
    } catch (error) {
      setFailedAiRun("alternatives");
      setMessage(`替代方案生成失败：${error instanceof Error ? error.message : "请确认 Path Agent 配置"}。`);
    } finally {
      await refreshAgentRuns();
      setAiRunKind(null);
      setBusy(false);
    }
  }

  async function generateSynthesis() {
    setBusy(true);
    setAiRunStartedAt(new Date().toISOString());
    setAiRunKind("synthesis");
    setAiRunStep(0);
    setFailedAiRun(null);
    setMessage("");
    try {
      const data = await apiPost<CaseDetails>(`/api/cases/${activeCaseId}/synthesize`, { actor: currentIdentity.name, role: currentIdentity.role });
      setSynthesisReport(data.synthesis_report ?? null);
      setOwnerDecision(data.owner_decision ?? null);
      await refreshTimeline();
      setMessage("Synthesis Agent 已汇总所有成功与失败 Path，等待 Case Owner 决策。 ");
    } catch (error) {
      setFailedAiRun("synthesis");
      setMessage(`汇总报告生成失败：${error instanceof Error ? error.message : "请确认 Synthesis Agent 配置"}。`);
    } finally {
      await refreshAgentRuns();
      setAiRunKind(null);
      setBusy(false);
    }
  }

  async function decideCase(action: OwnerDecision["action"], guidance?: string) {
    const normalizedGuidance = guidance?.trim() ?? "";
    if (action === "MODIFY" && !normalizedGuidance) {
      setMessage("请先填写给 Orchestrator 的修改指导。 ");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const data = await apiPost<CaseDetails>(`/api/cases/${activeCaseId}/owner-decision`, {
          actor: currentIdentity.name,
          role: currentIdentity.role,
          action,
          guidance: action === "MODIFY" ? normalizedGuidance : undefined,
        });
      setCaseStatus(data.status);
      setPhase(data.phase);
      setOwnerDecision(data.owner_decision ?? null);
      setHumanProposal(data.human_proposal ?? initialHumanProposal);
      setSynthesisReport(data.synthesis_report ?? null);
      setCommitmentNodes(data.commitment_nodes ?? []);
      setPathAttempts(data.path_attempts ?? []);
      loadManifest(data.manifest, data.workflow_paths ?? []);
      await refreshTimeline();
      if (action === "MODIFY") {
        setShowModifyGuidance(false);
        setModifyGuidance("");
        automaticRunsRef.current.clear();
        setCaseRefreshKey((current) => current + 1);
      }
      const actionCopy = action === "CLOSE" ? "关闭 Case" : action === "KEEP_OPEN" ? "保持 Case Open" : "打回 Orchestrator 修改";
      setMessage(`${currentIdentity.name}已决定：${actionCopy}。`);
    } catch (error) {
      setMessage(`最终决策失败：${error instanceof Error ? error.message : "请确认当前身份与 Case 状态"}。`);
    } finally {
      setBusy(false);
    }
  }

  async function resetDemo() {
    setBusy(true);
    try {
      await apiPost<void>("/api/demo/reset", { dataset_id: "supply-chain-golden-path-v1" });
      setApproved(false);
      setPhase("INTAKE");
      setCapabilities(null);
      setShowCapabilities(false);
      setShowManifestYaml(false);
      setManifestYaml("");
      setManifestPaths([]);
      setManifestVersion(null);
      setShowApprovedManifest(false);
      setSelectedPathIds([]);
      setCommitmentNodes([]);
      setPathAttempts([]);
      setTimelineEvents([]);
      setAgentRuns([]);
      setPathAgentRuns([]);
      setSynthesisAgentRuns([]);
      setSynthesisReport(null);
      setOwnerDecision(null);
      setHumanProposal(initialHumanProposal);
      setShowModifyGuidance(false);
      setModifyGuidance("");
      setShowSynthesisTrace(false);
      setShowOrchestratorTrace(false);
      setExpandedPathTraces({});
      setCaseCreatedAt(new Date().toISOString());
      setCanViewManifest(true);
      setCaseStatus("OPEN");
      identityIndexRef.current = 0;
      setIdentityIndex(0);
      setApprovalReview(null);
      setFailedAiRun(null);
      automaticRunsRef.current.clear();
      setCaseRefreshKey((current) => current + 1);
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
      const data = await apiGet<CapabilityDetails>(
        `/api/cases/${activeCaseId}/capabilities`,
        { actor: currentIdentity.name, role: currentIdentity.role },
      );
      if (identityIndexRef.current !== requestIdentityIndex) return;
      setCapabilities(data);
    } catch {
      setShowCapabilities(false);
      setMessage("能力快照读取失败：请确认本地 API 已启动。 ");
    }
  }

  async function toggleManifestYaml() {
    if (showManifestYaml) {
      setShowManifestYaml(false);
      return;
    }
    setShowManifestYaml(true);
    if (manifestYaml) return;
    try {
      const requestIdentityIndex = identityIndex;
      const yaml = await apiGetText(
        `/api/cases/${activeCaseId}/manifest.yaml`,
        { actor: currentIdentity.name, role: currentIdentity.role },
      );
      if (identityIndexRef.current !== requestIdentityIndex) return;
      setManifestYaml(yaml);
    } catch {
      setShowManifestYaml(false);
      setMessage("Manifest YAML 读取失败：请确认本地 API 已启动。 ");
    }
  }

  async function copyManifestYaml() {
    if (!manifestYaml) return;
    try {
      await navigator.clipboard.writeText(manifestYaml);
      setMessage("完整 Manifest YAML 已复制。 ");
    } catch {
      setMessage("复制失败，请直接选择 YAML 文本。 ");
    }
  }

  async function decideCommitment(caseId: string, node: CommitmentNode, decision: CommitmentDecision) {
    setBusy(true);
    setMessage("");
    try {
      const data = await apiPost<CaseDetails>(
        `/api/cases/${caseId}/paths/${node.path_id}/commitments/${node.id}/decision`,
        { actor: currentIdentity.name, role: currentIdentity.role, decision },
      );
      if (caseId === activeCaseId) {
        setCommitmentNodes(data.commitment_nodes ?? []);
        setPathAttempts(data.path_attempts ?? []);
        setPhase(data.phase);
        await refreshTimeline();
      }
      setApprovalReview(null);
      const result = decision === "APPROVE" ? "通过" : decision === "REVISE" ? "要求修改" : "否决";
      setMessage(`${currentIdentity.name} 已${result} ${caseId} 的 ${node.id} 节点。`);
    } catch {
      setMessage("审批操作失败：请确认当前身份、节点状态与本地 API。 ");
    } finally {
      setBusy(false);
    }
  }

  const phaseStageIndex: Record<string, number> = {
    INTAKE: 0,
    MANIFEST_REVIEW: 1,
    PATH_EXPLORATION: 2,
    PROFESSIONAL_COMMITMENT: 3,
    FINAL_REVIEW: 4,
  };
  const activeStageIndex = phaseStageIndex[phase] ?? 0;
  const isCaseClosed = caseStatus === "CLOSED";
  const currentStage = isCaseClosed ? "Case 已关闭" : stages[activeStageIndex];
  const synthesisRevision = synthesisReport?.revision ?? ownerDecision?.synthesis_revision;
  const pendingExplorationPathIds = manifestPaths
    .filter((path) => path.selected)
    .filter((path) => {
      const attempt = pathAttempts.find((item) => item.path_id === path.id);
      return !attempt || attempt.state === "REVISING" || !isSolutionRevision(attempt.solution_revision);
    })
    .map((path) => path.id);
  const completedExplorationCount = manifestPaths.filter((path) => path.selected).length - pendingExplorationPathIds.length;
  const selectedPathViews = manifestPaths.filter((path) => path.selected).map((path) => {
    const attempt = pathAttempts.find((item) => item.path_id === path.id);
    const revision = isSolutionRevision(attempt?.solution_revision) ? attempt.solution_revision : null;
    const nodes = commitmentNodes.filter((node) => node.path_id === path.id);
    const runs = pathAgentRuns.filter((run) => run.events.some(
      (event) => event.step === "run.started" && event.details.path_id === path.id,
    ));
    return { path, revision, nodes, runs };
  });
  const liveAgentType = aiRunKind === "manifest" ? "orchestrator" : aiRunKind === "alternatives" ? "path" : "synthesis";
  const allLiveAgentRuns = liveAgentType === "orchestrator"
    ? agentRuns
    : liveAgentType === "path" ? pathAgentRuns : synthesisAgentRuns;
  const liveAgentRuns = aiRunStartedAt
    ? allLiveAgentRuns.filter((run) => run.started_at >= aiRunStartedAt)
    : [];
  const latestFailedOrchestratorRuns = agentRuns[0]?.status === "FAILED" ? [agentRuns[0]] : [];
  const latestFailedPathRuns = pathAgentRuns[0]?.status === "FAILED" ? [pathAgentRuns[0]] : [];
  const latestFailedSynthesisRuns = synthesisAgentRuns[0]?.status === "FAILED" ? [synthesisAgentRuns[0]] : [];
  const latestFailedRunCount = latestFailedOrchestratorRuns.length
    + latestFailedPathRuns.length
    + latestFailedSynthesisRuns.length;
  const hasApprovedManifest = canViewManifest
    && manifestPaths.length > 0
    && ["PATH_EXPLORATION", "PROFESSIONAL_COMMITMENT", "FINAL_REVIEW"].includes(phase);

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

  function openApprovalReview(
    caseId: string,
    caseTitle: string,
    pathTitle: string,
    node: CommitmentNode,
    context: ApprovalContext,
  ) {
    setApprovalReview({ caseId, caseTitle, pathTitle, node, context });
  }

  function approvalReviewButton(
    caseId: string,
    caseTitle: string,
    pathTitle: string,
    node: CommitmentNode,
    context: ApprovalContext,
  ) {
    if (node.status !== "PENDING" || node.role !== currentIdentity.role) return null;
    return (
      <button
        className="reviewEvidenceButton"
        onClick={() => openApprovalReview(caseId, caseTitle, pathTitle, node, context)}
      >
        查看审批依据 →
      </button>
    );
  }

  function commitmentNode(node: CommitmentNode, revision: SolutionRevision | null, pathTitle: string) {
    const statusLabel = node.status === "PENDING"
      ? node.role === currentIdentity.role ? "待本人批准" : `待${node.role}批准`
      : node.status === "BLOCKED" ? "等待前置审批"
      : node.status === "READY" ? "已通过"
      : node.status === "STALE" ? "待方案修改"
      : node.status === "REJECTED" ? "已否决"
      : node.status;
    return (
      <article className={`dagNode ${node.depends_on.length ? "downstream" : "upstream"} ${node.status.toLowerCase()}`} key={`${node.path_id}-${node.id}`}>
        <span>{statusLabel}</span>
        <h3>{node.role}</h3>
        <p>{commitmentCopy[node.id] ?? "等待责任人确认"}</p>
        {approvalReviewButton(
          activeCaseId,
          caseDetails?.title ?? activeCaseId,
          pathTitle,
          node,
          approvalContextFor(revision, node.role),
        )}
        {approvalActions(activeCaseId, node)}
      </article>
    );
  }

  const orchestrationCard = aiRunKind ? (
    <AiWorkingCard
      kind={aiRunKind}
      step={aiRunStep}
      runs={liveAgentRuns}
      paths={aiRunKind === "alternatives" ? manifestPaths.filter((path) => aiPathIds.includes(path.id)) : []}
      executionMode={pathExecutionMode}
      maxConcurrency={pathMaxConcurrency}
    />
  ) : phase === "MANIFEST_REVIEW" && !canViewManifest ? (
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
  ) : phase === "PATH_EXPLORATION" ? (
    <>
      <div className="panelTitle">
        <div><span className="agentIcon">◇</span><span><small>PATH EXPLORATION</small><h2>探索已批准的 Path</h2></span></div>
        <span className="version">{completedExplorationCount} / {manifestPaths.filter((path) => path.selected).length} READY</span>
      </div>
      <p className="lead">Path Agent 正在为每条已选 Path 形成独立的 SolutionRevision。全部完成后，本阶段自动结束，平台才会开放专业承诺审批。</p>
      <div className="pathExplorationProgress" aria-label="Path 探索进度">
        {manifestPaths.filter((path) => path.selected).map((path) => {
          const attempt = pathAttempts.find((item) => item.path_id === path.id);
          const complete = isSolutionRevision(attempt?.solution_revision) && attempt?.state !== "REVISING";
          return (
            <article className={complete ? "complete" : "pending"} key={path.id}>
              <span>{complete ? "✓" : "AI"}</span>
              <div><strong>{path.title}</strong><small>{complete ? "SolutionRevision 已就绪" : attempt?.state === "REVISING" ? "根据专业意见重新推演" : "等待 Path Agent 完成"}</small></div>
            </article>
          );
        })}
      </div>
      <div className="explorationGate">
        <strong>阶段出口</strong>
        <p>所有已选 Path 均产出可审查方案 → 进入“专业承诺”并开放审批 DAG。</p>
      </div>
      {failedAiRun === "alternatives" && (
        <button className="primary explorationRetry" disabled={busy || pendingExplorationPathIds.length === 0} onClick={() => generateAlternatives(pendingExplorationPathIds)}>重试未完成的 Path Agent</button>
      )}
    </>
  ) : phase === "PROFESSIONAL_COMMITMENT" ? (
    <>
      <div className="panelTitle">
        <div><span className="agentIcon">✓</span><span><small>PROFESSIONAL COMMITMENT</small><h2>专业承诺 · 审批 DAG</h2></span></div>
        <span className="version">{selectedPathViews.length} PATHS</span>
      </div>
      <p className="lead">Path 卡片只保留所有角色共享的方案摘要。轮到本人审批时，从责任节点打开专属依据与决策面板；Agent 不能代替审批。</p>
      <div className="pathApprovalList">
        {selectedPathViews.map(({ path, revision, nodes, runs }) => {
          const rootNodes = nodes.filter((node) => node.depends_on.length === 0);
          const downstreamNodes = nodes.filter((node) => node.depends_on.length > 0);
          const completedNodes = nodes.filter((node) => node.status === "READY").length;
          return (
            <section className="pathApprovalGroup" aria-label={`${path.title} 审批 DAG`} key={path.id}>
              <header className="pathApprovalHeader">
                <span><strong>{pathLabel(path)}</strong></span>
                <em>{completedNodes} / {nodes.length} 已通过</em>
              </header>
              {revision ? (
                <section className="solutionRevision sharedSolution" aria-label={`${path.title} 共同方案摘要`}>
                  <div className="solutionHeader">
                    <span><small>SHARED SOLUTION BRIEF</small><strong>v{revision.revision} · 共同方案摘要</strong></span>
                    <em>{revision.generated_by}</em>
                  </div>
                  <p>{revision.summary}</p>
                  <div className="solutionOptions">
                    {revision.options.map((option) => (
                      <article key={option.id}>
                        <span>{option.id}</span>
                        <h3>{option.title}</h3>
                        <p>{option.description}</p>
                      </article>
                    ))}
                  </div>
                  <div className="solutionRecommendation">
                    <strong>Agent 建议（非业务决定）</strong>
                    <p>{revision.recommendation.rationale}</p>
                    <small>推荐选项：{revision.recommendation.option_ids.join("、") || "待责任角色核验"}</small>
                  </div>
                  {runs.length > 0 && (
                    <>
                      <button
                        className="linkButton traceToggle"
                        onClick={() => setExpandedPathTraces((current) => ({
                          ...current,
                          [path.id]: !current[path.id],
                        }))}
                      >
                        {expandedPathTraces[path.id]
                          ? `收起 ${path.title} Trace ↑`
                          : `查看 ${path.title} Trace (${runs.length}) →`}
                      </button>
                      {expandedPathTraces[path.id] && <AgentTracePanel runs={runs} agentType="path" />}
                    </>
                  )}
                </section>
              ) : <p className="autoRunNote">该 Path 尚缺少可审查的 SolutionRevision。</p>}
              <div className={`dag ${rootNodes.length === 1 ? "singleRoot" : ""}`} aria-label={`${path.title} Commitment DAG`}>
                {rootNodes.map((node) => commitmentNode(node, revision, path.title))}
                {downstreamNodes.length > 0 && <div className="dagJoin"><i /><i /></div>}
                {downstreamNodes.map((node) => commitmentNode(node, revision, path.title))}
              </div>
            </section>
          );
        })}
      </div>
      <div className="metricStrip">
        <span><strong>{selectedPathViews.length}</strong><small>selected Paths</small></span>
        <span><strong>{commitmentNodes.length}</strong><small>commitment nodes</small></span>
        <span><strong>{commitmentNodes.filter((node) => node.status === "PENDING").length}</strong><small>ready for human review</small></span>
      </div>
      {canViewManifest && (
        <>
          <button className="linkButton capabilityToggle" onClick={toggleCapabilities}>{showCapabilities ? "收起能力快照 ↑" : "查看本次能力快照 →"}</button>
          {showCapabilities && capabilities && <CapabilityPanel details={capabilities} />}
        </>
      )}
    </>
  ) : phase === "FINAL_REVIEW" ? (
    <>
      <div className="panelTitle">
        <div><span className="agentIcon">∑</span><span><small>CASE SYNTHESIS</small><h2>全 Path 汇总 · Owner 决策</h2></span></div>
        <span className="version">{synthesisRevision ? `v${synthesisRevision}` : "等待汇总"}</span>
      </div>
      {!canViewManifest ? (
        <p className="lead">{isCaseClosed
          ? `Case Owner 已基于 Synthesis v${synthesisRevision ?? "—"} 完成最终决策并关闭 Case。汇总报告仅对 Case Owner 可见。`
          : "所有 Path 的审批 DAG 已完成。汇总报告与最终决策仅对 Case Owner 可见。"}</p>
      ) : synthesisReport ? (
        <section className="synthesisReport" aria-label="Synthesis Agent 汇总报告">
          <div className="synthesisHeader">
            <span><small>SYNTHESIS REPORT</small><strong>{synthesisReport.summary}</strong></span>
            <em>{synthesisReport.generated_by}</em>
          </div>
          <div className="pathAssessmentGrid">
            {synthesisReport.path_assessments.map((assessment) => {
              const path = manifestPaths.find((item) => item.id === assessment.path_id);
              return (
                <article className={assessment.status.toLowerCase()} key={assessment.path_id}>
                  <span>{assessment.status === "SUCCEEDED" ? "审批成功" : "审批失败"}</span>
                  <h3>{path?.title ?? assessment.path_id}</h3>
                  <p>{assessment.conclusion}</p>
                  <small>依据：{assessment.supporting_refs.join(" · ")}</small>
                  {assessment.risks.length > 0 && <small>风险：{assessment.risks.join("；")}</small>}
                </article>
              );
            })}
          </div>
          <div className="synthesisFindings">
            <div><strong>跨 Path 结论</strong><p>{synthesisReport.cross_path_findings.join("；") || "无新增结论"}</p></div>
            <div><strong>剩余风险</strong><p>{synthesisReport.remaining_risks.join("；") || "未记录剩余风险"}</p></div>
          </div>
          <div className="ownerDecisionBrief">
            <span><small>AGENT 建议 · 非最终决定</small><strong>{synthesisReport.recommended_owner_action}</strong></span>
            <p>{synthesisReport.decision_brief}</p>
          </div>
          {ownerDecision && (
            <p className="decisionRecorded">最近决定：{ownerDecision.action} · {formatThreadTime(ownerDecision.decided_at)}</p>
          )}
          <div className="ownerDecisionActions" aria-label="Case Owner 最终决策">
            <button className="decisionClose" disabled={busy || caseStatus === "CLOSED"} onClick={() => decideCase("CLOSE")}>关闭 Case</button>
            <button className="decisionOpen" disabled={busy || caseStatus === "CLOSED"} onClick={() => decideCase("KEEP_OPEN")}>保持 Open</button>
            <button className="decisionModify" disabled={busy || caseStatus === "CLOSED"} onClick={() => setShowModifyGuidance((current) => !current)}>修改方案</button>
          </div>
          {showModifyGuidance && caseStatus !== "CLOSED" && (
            <div className="modifyGuidance" aria-label="给 Orchestrator 的修改指导">
              <label htmlFor="orchestrator-guidance">告诉 Orchestrator 下一轮应如何调整</label>
              <textarea
                id="orchestrator-guidance"
                value={modifyGuidance}
                onChange={(event) => setModifyGuidance(event.target.value)}
                placeholder="例如：保留物料替代 Path，同时重点探索不需要客户重新认证的交付拆分方案。"
                rows={4}
              />
              <small>这段文字会成为新版 Human Proposal，并进入下一轮 Orchestrator 上下文。</small>
              <div>
                <button className="ghost" disabled={busy} onClick={() => { setShowModifyGuidance(false); setModifyGuidance(""); }}>取消</button>
                <button className="primary" disabled={busy || !modifyGuidance.trim()} onClick={() => decideCase("MODIFY", modifyGuidance)}>提交指导并重新编排</button>
              </div>
            </div>
          )}
          {synthesisAgentRuns.length > 0 && (
            <>
              <button className="linkButton traceToggle" onClick={() => setShowSynthesisTrace((current) => !current)}>
                {showSynthesisTrace ? "收起 Synthesis Trace ↑" : `查看 Synthesis Trace (${synthesisAgentRuns.length}) →`}
              </button>
              {showSynthesisTrace && <AgentTracePanel runs={synthesisAgentRuns} agentType="synthesis" />}
            </>
          )}
        </section>
      ) : (
        <div className="explorationGate">
          <strong>全部审批 DAG 已完成</strong>
          <p>Synthesis Agent 将读取所有成功与失败 Path 的 SolutionRevision 和人类审批结果，不会补造新证据。</p>
          {failedAiRun === "synthesis" && <button className="primary explorationRetry" disabled={busy} onClick={generateSynthesis}>重试 Synthesis Agent</button>}
        </div>
      )}
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
        <h3>{caseDetails?.title ?? "正在同步 Case"}</h3>
        <p>{caseDetails?.description ?? "Case 事实加载完成后，Orchestrator 才会开始规划。"}</p>
      </article>
      <div className="approvalBox">
        <span><strong>{failedAiRun === "manifest" ? "自动规划已暂停" : "AI 将自动开始规划"}</strong><small>Planner 无权发明 Path、删除强制责任或作出业务承诺。</small></span>
        {failedAiRun === "manifest" && <button className="primary" disabled={busy} onClick={generateManifest}>重试 AI 规划</button>}
      </div>
    </>
  ) : (
    <>
      <div className="panelTitle">
        <div><span className="agentIcon">✦</span><span><small>ORCHESTRATOR 建议</small><h2>审查 Path Manifest</h2></span></div>
        <span className="version">v1 · 待批准</span>
      </div>
      <p className="lead">Orchestrator 已为每条候选 Path 选择本次采用的 Skill。Owner 可以选择本轮真正进入探索的 Path。</p>
      <div className="pathChoices">
        {manifestPaths.map((path, index) => {
          const selected = selectedPathIds.includes(path.id);
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
              <h3>{pathLabel(path)}</h3>
              <p>{path.rationale}</p>
              <div className="pathStats">
                <span><small>强制 Policy</small><strong>{path.policies.length}</strong></span>
                <span><small>Agent 选择</small><strong>{path.skill_selections.length}</strong></span>
                <span><small>参考 Knowledge</small><strong>{path.knowledge.length}</strong></span>
              </div>
              <div className="manifestSkillChoices">
                {path.skill_selections.map((selection) => (
                  <details className="manifestSkillChoice" key={selection.entrypoint.id}>
                    <summary>
                      <strong>{skillLabel(selection.entrypoint, selection.title)}</strong>
                      <span>{selection.members.length ? "SKILL BUNDLE" : "ATOMIC SKILL"}</span>
                    </summary>
                    <p><b>选择理由</b>{selection.reason ?? "历史 Manifest 未记录选择理由"}</p>
                    {selection.members.length > 0 && (
                      <div>
                        <b>Bundle 成员</b>
                        {selection.members.map((member) => <code key={member.id}>{skillLabel(member)}</code>)}
                      </div>
                    )}
                  </details>
                ))}
              </div>
            </article>
          );
        })}
      </div>
      <button className="linkButton capabilityToggle" onClick={toggleManifestYaml}>{showManifestYaml ? "收起完整 Manifest YAML ↑" : "查看完整 Manifest YAML →"}</button>
      {showManifestYaml && manifestYaml && (
        <ManifestYamlPanel
          yaml={manifestYaml}
          onCopy={copyManifestYaml}
          downloadHref={apiUrl(`/api/cases/${activeCaseId}/manifest.yaml`, { actor: currentIdentity.name, role: currentIdentity.role })}
        />
      )}
      <div className="approvalBox">
        <span><strong>批准范围 · 已选 {selectedPathIds.length} 条</strong><small>只为勾选的 Path 创建 PathAttempt，不代表批准最终业务方案。</small></span>
        <button className="primary" disabled={busy || selectedPathIds.length === 0} onClick={approveManifest}>{busy ? "处理中…" : "批准并启动所选 Path"}</button>
      </div>
    </>
  );

  return (
    <main className="shell">
      <AppSidebar
        active="none"
        identity={currentIdentity}
        identities={demoIdentities}
        busy={busy}
        onIdentitySelect={selectIdentity}
      />

      <section className="workspace">
        <header className="topbar">
          <div className="breadcrumbs"><Link href="/">Case 总览</Link> <span>/</span> {caseDetails?.id ?? activeCaseId}</div>
          <div className="topActions"><button className="ghost">审计记录</button><button className="ghost" disabled={busy} onClick={resetDemo}>重置 Demo</button></div>
        </header>
        <div className="content">
          <header className="issueHeader">
            <div>
              <div className="eyebrow">SUPPLY CHAIN CASE <span>·</span> {caseDetails?.business_payload?.risk_level === "HIGH" ? "高" : caseDetails?.business_payload?.risk_level === "LOW" ? "低" : "中"}优先级</div>
              <h1>{caseDetails?.title ?? "正在加载 Case"} <span>#{caseDetails?.id ?? activeCaseId}</span></h1>
              <p><span className={`openBadge ${caseStatus.toLowerCase()}`}>● {caseStatus === "CLOSED" ? "Closed" : "Open"}</span> {caseDetails?.owner ?? "Case Owner"} 于 {formatThreadTime(caseCreatedAt)} 创建 · 当前由 <strong>{caseDetails?.owner ?? "—"}</strong> 负责</p>
            </div>
            <button className="primary">继续处理 <span>→</span></button>
          </header>

          <div className="mainGrid threadLayout">
            <section className="caseThread" aria-label="Case 完整流转 Thread">
              {message && <div className="toast" role="status">{message}</div>}

              <article className="threadItem commentItem">
                <PersonIcon name={humanProposal.author} fallback="陈" className="threadAvatar humanAvatar" />
                <div className="commentBox">
                  <header><strong>{humanProposal.author}</strong><span>Case Owner · {formatThreadTime(caseCreatedAt)}</span><b>Human Proposal v{humanProposal.revision}</b></header>
                  <div className="commentBody">
                    <p>{caseDetails?.description ?? "正在同步 Case 事实。"}</p>
                    <h3>Human Proposal</h3>
                    <blockquote>{humanProposal.content}</blockquote>
                    <div className="factChips">
                      {caseDetails?.business_payload?.material && <span>{caseDetails.business_payload.material}</span>}
                      {caseDetails?.business_payload?.gap_quantity !== undefined && <span>缺口 {formatQuantity(caseDetails.business_payload.gap_quantity)} pcs</span>}
                      {caseDetails?.business_payload?.target_date && <span>目标 {caseDetails.business_payload.target_date}</span>}
                    </div>
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
                      <BotIcon kind="orchestrator" className="eventIcon botEvent" />
                      <p><strong>Orchestrator 生成 Manifest v{event.details.revision ?? 1}</strong><span>匹配组织能力并冻结 Policy / Skill / Knowledge 快照 · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                if (event.event_type === "manifest.approved") {
                  return (
                    <div className="threadEvent completedEvent" key={event.id}>
                      <PersonIcon name={event.details.actor} fallback={event.details.actor?.slice(0, 1) ?? "人"} className="eventIcon humanEvent" />
                      <p><strong>{event.details.actor ?? "Case Owner"} 批准 Manifest</strong><span>启动已批准的 PathAttempt，最终业务决定尚未作出 · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                if (event.event_type === "solution_revision.proposed") {
                  const explorationCompleted = event.details.next_phase === "PROFESSIONAL_COMMITMENT";
                  return (
                    <div className="threadEvent completedEvent" key={event.id}>
                      <BotIcon kind="path" className="eventIcon botEvent" />
                      <p><strong>Path Agent 生成 SolutionRevision v{event.details.revision ?? 1}</strong><span>{event.details.path_id} · {event.details.option_count ?? 0} 个可审查选项；{explorationCompleted ? "Path 探索完成，进入专业承诺" : "继续探索其余 Path"} · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                if (event.event_type === "commitment.approved") {
                  return (
                    <div className="threadEvent completedEvent" key={event.id}>
                      <PersonIcon name={event.details.actor} fallback={event.details.actor?.slice(0, 1) ?? "人"} className="eventIcon humanEvent" />
                      <p><strong>{event.details.actor}（{event.details.role}）批准 {event.details.node_id}</strong><span>{commitmentCopy[event.details.node_id ?? ""] ?? "专业责任节点"}已确认，节点变为 READY · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                if (event.event_type === "commitment.revision_requested" || event.event_type === "commitment.rejected") {
                  const isRevision = event.event_type === "commitment.revision_requested";
                  return (
                    <div className="threadEvent" key={event.id}>
                      <PersonIcon name={event.details.actor} fallback={event.details.actor?.slice(0, 1) ?? "人"} className="eventIcon humanEvent" />
                      <p><strong>{event.details.actor}（{event.details.role}）{isRevision ? "要求修改" : "否决"} {event.details.node_id}</strong><span>{isRevision ? "PathAttempt 进入 REVISING" : "当前 PathAttempt 已结束"} · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                if (event.event_type === "synthesis.proposed") {
                  return (
                    <div className="threadEvent completedEvent" key={event.id}>
                      <BotIcon kind="synthesis" className="eventIcon botEvent" />
                      <p><strong>Synthesis Agent 生成汇总报告 v{event.details.revision ?? 1}</strong><span>{event.details.successful_path_count ?? 0} 条成功 · {event.details.failed_path_count ?? 0} 条失败；等待 Case Owner 决策 · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                if (event.event_type === "owner.decision") {
                  const copy = event.details.action === "CLOSE" ? "关闭 Case" : event.details.action === "KEEP_OPEN" ? "保持 Case Open" : "修改并打回 Orchestrator";
                  return (
                    <div className="threadEvent completedEvent" key={event.id}>
                      <PersonIcon name={event.details.actor} fallback={event.details.actor?.slice(0, 1) ?? "人"} className="eventIcon humanEvent" />
                      <p><strong>{event.details.actor ?? "Case Owner"} 决定：{copy}</strong><span>{event.details.guidance ? `指导：${event.details.guidance} · ` : ""}基于 Synthesis v{event.details.synthesis_revision ?? 1} · {formatThreadTime(event.created_at)}</span></p>
                    </div>
                  );
                }
                return null;
              })}

              <article className="threadItem commentItem currentThreadItem">
                <BotIcon kind={phase === "FINAL_REVIEW" ? "synthesis" : phase === "PATH_EXPLORATION" ? "path" : "orchestrator"} className="threadAvatar botAvatar" />
                <div className="commentBox activeComment">
                  <header><strong>Agentic CM</strong><span>{phase === "FINAL_REVIEW" ? "Synthesis Agent" : phase === "PROFESSIONAL_COMMITMENT" ? "Commitment Workflow" : approved ? "Path Agent" : "Orchestrator"} · 当前步骤</span><b className="currentLabel">{currentStage}</b></header>
                  <div className="commentBody actionBody">
                    {orchestrationCard}
                    {hasApprovedManifest && (
                      <section className={`approvedManifestArchive ${showApprovedManifest ? "expanded" : ""}`} aria-label="已批准 Manifest">
                        <header>
                          <span className="approvedManifestIcon">M</span>
                          <span>
                            <small>CASE KEY MATERIAL · FROZEN</small>
                            <strong>已批准 Manifest{manifestVersion ? ` v${manifestVersion}` : ""}</strong>
                            <p>{manifestPaths.filter((path) => path.selected).length} 条 Path 已批准进入本轮探索 · 原始理由与能力快照持续保留</p>
                          </span>
                          <button
                            type="button"
                            aria-expanded={showApprovedManifest}
                            onClick={() => setShowApprovedManifest((current) => !current)}
                          >
                            {showApprovedManifest ? "收起 Manifest ↑" : "查看已批准 Manifest →"}
                          </button>
                        </header>
                        {showApprovedManifest && (
                          <div className="approvedManifestBody">
                            <p className="manifestBoundary">这是批准时冻结的 Manifest，只用于查阅与审计；后续 Path 结果和专业审批不会改写这份材料。</p>
                            <div className="approvedManifestPaths">
                              {manifestPaths.map((path, index) => {
                                return (
                                  <article className={path.selected ? "selected" : "notSelected"} key={path.id}>
                                    <div>
                                      <span>PATH {String(index + 1).padStart(2, "0")}</span>
                                      <em>{path.selected ? "已批准" : "本轮未选"}</em>
                                    </div>
                                    <h3>{pathLabel(path)}</h3>
                                    <p>{path.rationale || "Manifest 未记录额外理由。"}</p>
                                    <dl>
                                      <div><dt>Policy</dt><dd>{path.policies.length}</dd></div>
                                      <div><dt>Agent 选择</dt><dd>{path.skill_selections.length}</dd></div>
                                      <div><dt>Knowledge</dt><dd>{path.knowledge.length}</dd></div>
                                    </dl>
                                  </article>
                                );
                              })}
                            </div>
                            <button className="linkButton capabilityToggle" onClick={toggleManifestYaml}>
                              {showManifestYaml ? "收起完整 Manifest YAML ↑" : "查看完整 Manifest YAML →"}
                            </button>
                            {showManifestYaml && manifestYaml && (
                              <ManifestYamlPanel
                                yaml={manifestYaml}
                                onCopy={copyManifestYaml}
                                downloadHref={apiUrl(`/api/cases/${activeCaseId}/manifest.yaml`, { actor: currentIdentity.name, role: currentIdentity.role })}
                              />
                            )}
                          </div>
                        )}
                      </section>
                    )}
                    {canViewManifest && latestFailedRunCount > 0 && (
                      <section className="failedAgentTraces" aria-label="最新失败 Agent Trace">
                        <header>
                          <span><small>AGENT FAILURE</small><strong>最新失败运行 · Trace 已自动展开</strong></span>
                          <em>{latestFailedRunCount} FAILED</em>
                        </header>
                        {latestFailedOrchestratorRuns.length > 0 && (
                          <AgentTracePanel runs={latestFailedOrchestratorRuns} agentType="orchestrator" autoExpand />
                        )}
                        {latestFailedPathRuns.length > 0 && (
                          <AgentTracePanel runs={latestFailedPathRuns} agentType="path" autoExpand />
                        )}
                        {latestFailedSynthesisRuns.length > 0 && (
                          <AgentTracePanel runs={latestFailedSynthesisRuns} agentType="synthesis" autoExpand />
                        )}
                      </section>
                    )}
                    {canViewManifest && agentRuns.some((run) => run.agent_type === "orchestrator") && (
                      <>
                        <button className="linkButton traceToggle" onClick={() => setShowOrchestratorTrace((current) => !current)}>
                          {showOrchestratorTrace
                            ? "收起 Orchestrator Trace ↑"
                            : `${agentRuns.some((run) => run.status === "FAILED") ? "查看失败" : "查看"} Orchestrator Trace (${agentRuns.filter((run) => run.agent_type === "orchestrator").length}) →`}
                        </button>
                        {showOrchestratorTrace && (
                          <AgentTracePanel runs={agentRuns} agentType="orchestrator" />
                        )}
                      </>
                    )}
                  </div>
                </div>
              </article>

              {activeStageIndex < 4 && (
                <div className="futureFlow" aria-label="后续流程">
                  {activeStageIndex < 3 && <div><span>4</span><p><strong>专业承诺汇合</strong><small>Path 探索完成后开放；供应与技术并行评审</small></p></div>}
                  <div><span>5</span><p><strong>Case Owner 最终决策</strong><small>基于 Synthesis 报告选择关闭、保持 Open 或打回修改</small></p></div>
                </div>
              )}
            </section>

            <aside className="rightRail">
              <section className="panel flowSummary">
                <div className="compactTitle"><h2>完整流程</h2><span>{activeStageIndex + 1} / {stages.length}</span></div>
                <ol>
                  {stages.map((stage, index) => (
                    <li className={index < activeStageIndex || (isCaseClosed && index === activeStageIndex) ? "complete" : index === activeStageIndex ? "current" : ""} key={stage}>
                      <span>{index < activeStageIndex || (isCaseClosed && index === activeStageIndex) ? "✓" : index + 1}</span>
                      <div><strong>{stage}</strong><small>{index < activeStageIndex || (isCaseClosed && index === activeStageIndex) ? "已完成" : index === activeStageIndex ? "进行中" : "尚未开始"}</small></div>
                    </li>
                  ))}
                </ol>
              </section>
              <section className="panel facts">
                <div className="compactTitle"><h2>Case 事实</h2><button>查看全部</button></div>
                <dl>
                  <div><dt>Case Owner</dt><dd>{caseDetails?.owner ?? "—"}</dd></div>
                  <div><dt>订单</dt><dd>{caseDetails?.business_payload?.order_id ?? "—"}</dd></div>
                  <div><dt>客户</dt><dd>{caseDetails?.business_payload?.customer ?? "—"}</dd></div>
                  <div><dt>关键物料</dt><dd>{caseDetails?.business_payload?.material ?? "—"}</dd></div>
                  <div><dt>缺口数量</dt><dd>{caseDetails?.business_payload?.gap_quantity !== undefined ? `${formatQuantity(caseDetails.business_payload.gap_quantity)} pcs` : "—"}</dd></div>
                  <div><dt>目标交付日</dt><dd>{caseDetails?.business_payload?.target_date ?? "—"}</dd></div>
                </dl>
              </section>
              <section className="notice"><strong>演示安全边界</strong><p>不连接或修改 ERP、库存、订单及客户系统；所有执行均为 sandbox 推演。</p></section>
            </aside>
          </div>
        </div>
      </section>

      {approvalReview && (
        <div
          className="approvalReviewBackdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setApprovalReview(null);
          }}
        >
          <aside
            className="approvalReviewPanel"
            role="dialog"
            aria-modal="true"
            aria-label={`${approvalReview.node.role} 审批依据`}
          >
            <header>
              <div>
                <small>ROLE-SCOPED EVIDENCE · {approvalReview.node.id}</small>
                <h2>{approvalReview.node.role}审批依据</h2>
                <p>{approvalReview.caseId} · {approvalReview.pathTitle}</p>
              </div>
              <button aria-label="关闭审批依据" onClick={() => setApprovalReview(null)}>×</button>
            </header>
            <div className="approvalReviewBody">
              <section className="approvalScope">
                <small>本次责任边界</small>
                <strong>{commitmentCopy[approvalReview.node.id] ?? "确认本节点专业判断"}</strong>
                <p>你只批准本节点对应的专业判断，不代表其他角色，也不执行任何业务动作。</p>
              </section>
              <section className="evidenceSection roleEvidence">
                <small>你的专业判断与证据摘要</small>
                <h3>{approvalReview.context.role_report?.dimension ?? "对应角色报告尚未生成"}</h3>
                <p>{approvalReview.context.role_report?.report ?? "当前没有可供本角色审查的报告，请选择“修改”要求补充。"}</p>
              </section>
              <section className="evidenceSection">
                <small>共同方案上下文 · REVISION {approvalReview.context.revision ?? "—"}</small>
                <p>{approvalReview.context.summary}</p>
                <div className="evidenceOptions">
                  {approvalReview.context.options.map((option) => (
                    <article key={option.id}>
                      <span>{option.id}</span>
                      <div><strong>{option.title}</strong><p>{option.description}</p></div>
                    </article>
                  ))}
                </div>
                <div className="evidenceRecommendation">
                  <strong>Agent 建议（非业务决定）</strong>
                  <p>{approvalReview.context.recommendation.rationale || "暂无推荐意见。"}</p>
                </div>
              </section>
              <p className="roleEvidenceBoundary">其他角色的判断与证据在其责任节点审批时展示，不在本报告中展开。</p>
            </div>
            <footer>
              <span><small>当前身份</small><strong>{currentIdentity.name} · {currentIdentity.role}</strong></span>
              {approvalActions(approvalReview.caseId, approvalReview.node)}
            </footer>
          </aside>
        </div>
      )}
    </main>
  );
}
