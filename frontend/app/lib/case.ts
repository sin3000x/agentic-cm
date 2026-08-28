export const stages = ["Case 受理", "Manifest 评审", "Path 探索", "专业承诺", "最终决策"];

export const commitmentCopy: Record<string, string> = {
  SUPPLY: "确认 Manifest 候选物料的供应可行性",
  TECH: "确认 Manifest 候选物料的技术可行性",
  CUSTOMER: "确认客户接受度与整体建议",
  "EXPEDITE-SUPPLY": "确认供应商产能与最早可供应日期",
  "EXPEDITE-DELIVERY": "确认运输提速方案与预计到货日期",
  "SPLIT-PLAN": "确认可用数量与分批交付计划",
  "SPLIT-CUSTOMER": "确认客户对分批交付与剩余承诺的接受度",
};

export type CapabilityAsset = {
  id?: string;
  title?: string;
  version?: string;
  description?: string;
  instructions?: string[];
  requirements?: { commitments?: Array<{ role: string }> };
  content?: { summary?: string };
  resolved_ref: { id: string; version: string; source: string; digest: string };
};

export type CapabilityDetails = {
  snapshot_status: string;
  assets: {
    policies: CapabilityAsset[];
    skills: CapabilityAsset[];
    knowledge: CapabilityAsset[];
  };
};

export type ManifestAssetRef = {
  id: string;
  version: string;
  digest: string;
  title?: string;
};

export type ManifestSkillSelection = {
  entrypoint: ManifestAssetRef;
  reason: string | null;
  members: ManifestAssetRef[];
  title?: string;
};

export type ManifestPath = {
  id: string;
  definition: string;
  title: string;
  rationale: string;
  selected: boolean;
  policies: ManifestAssetRef[];
  skill_selections: ManifestSkillSelection[];
  knowledge: ManifestAssetRef[];
};

export type ManifestPathPayload = Omit<ManifestPath, "title" | "skill_selections"> & {
  title?: string;
  skill_selections?: ManifestSkillSelection[];
};

export type CommitmentNode = {
  id: string;
  role: string;
  review_dimension: string;
  status: "BLOCKED" | "PENDING" | "READY" | "STALE" | "REJECTED";
  depends_on: string[];
  path_id: string;
};

export type CommitmentDecision = "APPROVE" | "REVISE" | "REJECT";

export type SolutionOption = {
  id: string;
  title: string;
  description: string;
  benefits: string[];
  risks: string[];
  assumptions: string[];
};

export type SolutionRevision = {
  revision: number;
  summary: string;
  options: SolutionOption[];
  recommendation: { option_ids: string[]; rationale: string };
  evidence_gaps: string[];
  role_reports: Array<{ role: string; dimension: string; report: string }>;
  generated_by: string;
};

export type ApprovalContext = {
  revision: number | null;
  summary: string;
  options: SolutionOption[];
  recommendation: { option_ids?: string[]; rationale?: string };
  role_report: { role: string; dimension: string; report: string } | null;
};

export type ApprovalReview = {
  caseId: string;
  caseTitle: string;
  pathTitle: string;
  node: CommitmentNode;
  context: ApprovalContext;
};

export type PathAttempt = {
  path_id: string;
  state: "PLANNED" | "AWAITING_COMMITMENT" | "REVISING" | "SUCCEEDED" | "REJECTED";
  solution_revision: SolutionRevision | null;
};

export type SynthesisReport = {
  revision: number;
  summary: string;
  path_assessments: Array<{
    path_id: string;
    status: "SUCCEEDED" | "FAILED";
    conclusion: string;
    supporting_refs: string[];
    risks: string[];
  }>;
  cross_path_findings: string[];
  remaining_risks: string[];
  recommended_owner_action: "CLOSE" | "KEEP_OPEN" | "MODIFY";
  decision_brief: string;
  generated_by: string;
};

export type OwnerDecision = {
  action: "CLOSE" | "KEEP_OPEN" | "MODIFY";
  actor: string;
  role: string;
  synthesis_revision: number;
  decided_at: string;
};

export type HumanProposal = {
  revision: number;
  author: string;
  role: string;
  content: string;
};

export type PathExecutionMode = "parallel" | "serial";

export type PathExecutionResponse = {
  execution_mode: PathExecutionMode;
  max_concurrency: number;
  case: CaseDetails;
};

export type CaseStatusValue = "OPEN" | "CLOSED";
export type CasePhase =
  | "INTAKE"
  | "MANIFEST_REVIEW"
  | "PATH_EXPLORATION"
  | "PROFESSIONAL_COMMITMENT"
  | "FINAL_REVIEW";

export type CaseManifest = {
  id?: string;
  revision?: number;
  paths?: ManifestPathPayload[];
  knowledge?: ManifestAssetRef[];
};

export type CaseDetails = {
  id: string;
  title: string;
  description: string;
  owner: string;
  owner_role: string;
  business_payload?: {
    order_id?: string;
    customer?: string;
    material?: string;
    gap_quantity?: number;
    target_date?: string;
    risk_level?: "HIGH" | "MEDIUM" | "LOW";
  };
  status: CaseStatusValue;
  phase: CasePhase;
  version: number;
  created_at: string;
  updated_at?: string;
  human_proposal?: HumanProposal | null;
  manifest?: CaseManifest | null;
  workflow_paths?: ManifestPath[];
  path_attempts?: PathAttempt[];
  commitment_nodes?: CommitmentNode[];
  synthesis_report?: SynthesisReport | null;
  owner_decision?: OwnerDecision | null;
  permissions?: {
    can_view_manifest?: boolean;
    can_approve_manifest?: boolean;
    can_decide_case?: boolean;
  };
};

export type TimelineEvent = {
  id: number;
  event_type:
    | "manifest.proposed"
    | "manifest.approved"
    | "solution_revision.proposed"
    | "commitment.approved"
    | "commitment.revision_requested"
    | "commitment.rejected"
    | "synthesis.proposed"
    | "owner.decision";
  created_at: string;
  details: {
    revision?: number;
    actor?: string;
    role?: string;
    node_id?: string;
    path_id?: string;
    option_count?: number;
    next_phase?: string;
    successful_path_count?: number;
    failed_path_count?: number;
    action?: "CLOSE" | "KEEP_OPEN" | "MODIFY";
    synthesis_revision?: number;
    guidance?: string;
  };
};

export type AgentTraceEvent = {
  id: number;
  sequence: number;
  step: string;
  status: "STARTED" | "COMPLETED" | "FAILED";
  summary: string;
  details: Record<string, unknown>;
  created_at: string;
};

export type AgentRun = {
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

export type AiRunKind = "manifest" | "alternatives" | "synthesis";
export type PathRunUiStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";

export const initialHumanProposal: HumanProposal = {
  revision: 0,
  author: "Case Owner",
  role: "加载中",
  content: "正在同步 Case Owner 提案。",
};

export const aiRunCopy: Record<AiRunKind, { eyebrow: string; title: string; steps: string[] }> = {
  manifest: {
    eyebrow: "ORCHESTRATOR · LIVE",
    title: "Orchestrator Agent 正在为您组装探索清单",
    steps: ["读取 Case 事实", "匹配 Policy 与 Skill", "评估候选 Path", "固定能力引用"],
  },
  alternatives: {
    eyebrow: "PATH AGENT · LIVE",
    title: "Path Agent 正在为您推演解决方案",
    steps: ["校验 Manifest 引用", "运行执行 Skill", "比较收益与风险", "形成角色判断报告"],
  },
  synthesis: {
    eyebrow: "SYNTHESIS AGENT · LIVE",
    title: "Synthesis Agent 正在汇总全部 Path",
    steps: ["读取终态 Path", "对齐成功与失败", "归并风险与依据", "形成 Owner 决策简报"],
  },
};

export function pathLabel(path: Pick<ManifestPath, "title" | "definition">) {
  return path.title || path.definition;
}

export function skillLabel(asset: ManifestAssetRef, fallback?: string | null) {
  return asset.title || fallback || asset.id;
}

export function isSolutionRevision(value: unknown): value is SolutionRevision {
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

export function approvalContextFor(revision: SolutionRevision | null, role: string): ApprovalContext {
  return {
    revision: revision?.revision ?? null,
    summary: revision?.summary ?? "尚未读取到可审查的方案摘要。",
    options: revision?.options ?? [],
    recommendation: revision?.recommendation ?? {},
    role_report: revision?.role_reports.find((item) => item.role === role) ?? null,
  };
}

export function pathIdForRun(run: AgentRun) {
  const started = run.events.find((event) => event.step === "run.started");
  return typeof started?.details.path_id === "string" ? started.details.path_id : null;
}
