"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import AppSidebar from "./app-sidebar";
import { apiGet, isAbort } from "./lib/api";
import { botAvatars, personAvatars, useDemoIdentity } from "./lib/identities";
import { formatDay, formatDayTime } from "./lib/format";

type CaseStatus = "处理中" | "暂缓" | "已关闭";
type CaseRisk = "高" | "中" | "低";
type CaseSummary = {
  id: string;
  title: string;
  description: string;
  status: CaseStatus;
  risk: CaseRisk;
  owner: string;
  ownerRole: string;
  ownerInitial: string;
  customer: string;
  due: string;
  dueTone: "danger" | "warning" | "normal" | "muted";
  phase: number;
  phaseLabel: string;
  updated: string;
  attention?: string;
};
type ApiCase = {
  id: string;
  title: string;
  description: string;
  status: "OPEN" | "CLOSED";
  phase:
    | "INTAKE"
    | "MANIFEST_REVIEW"
    | "PATH_EXPLORATION"
    | "PROFESSIONAL_COMMITMENT"
    | "FINAL_REVIEW";
  owner: string;
  owner_role: string;
  business_payload?: {
    customer?: string;
    risk_level?: "HIGH" | "MEDIUM" | "LOW";
    commitment_due_date?: string;
  };
  commitment_nodes?: Array<{ status: string }>;
  updated_at: string;
};
const filters = ["全部", "处理中", "暂缓", "已关闭"] as const;
const stages = ["受理", "评审", "探索", "承诺", "决策"];

function HomeIcon({ name }: { name: "search" | "bell" | "plus" | "active" | "attention" | "check" | "cases" | "right" | "left" | "arrow" }) {
  const paths = {
    search: "M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
    bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4",
    plus: "M12 5v14M5 12h14",
    active: "M20 12a8 8 0 1 1-8-8M12 8v4l3 2M16 4h4v4",
    attention: "M12 8v5M12 17h.01M10.3 3.8 2.2 18a2 2 0 0 0 1.7 3h16.2a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0",
    check: "M8 12l3 3 5-6M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
    cases: "M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7h18",
    right: "m9 5 7 7-7 7",
    left: "m15 5-7 7 7 7",
    arrow: "M4 12h16m-6-6 6 6-6 6",
  };
  return <svg className="homeIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

function PhaseRing({ value, label, closed }: { value: number; label: string; closed: boolean }) {
  const description = closed ? "已关闭" : `当前阶段：${label}（${value}/${stages.length}）`;
  return (
    <span className="phaseRing" role="img" aria-label={description} title={description}>
      <svg viewBox="0 0 36 36" aria-hidden="true">
        {stages.map((stage, index) => (
          <circle key={stage} cx="18" cy="18" r="14" pathLength="100"
            fill="none" strokeWidth={index === value - 1 && !closed ? 3.5 : 2.5}
            strokeDasharray="16 84" strokeLinecap="round"
            transform={`rotate(${-86 + index * 72} 18 18)`}
            className={closed || index < value - 1 ? "phaseComplete" : index === value - 1 ? "phaseCurrent" : "phasePending"} />
        ))}
        {closed ? <path className="phaseCheck" d="m12 18 4 4 8-8" /> : <text x="18" y="18" dy=".35em" textAnchor="middle">{value}</text>}
      </svg>
    </span>
  );
}

function StatusPill({ status }: { status: CaseStatus }) {
  return <span className={`statusPill status-${status}`}>{status}</span>;
}
function RiskMark({ risk }: { risk: CaseRisk }) {
  return (
    <span className={`riskMark risk-${risk}`}>
      <i />
      {risk}风险
    </span>
  );
}
function StageProgress({ value, label }: { value: number; label: string }) {
  return (
    <div className="stageProgress" aria-label={`当前阶段：${label}`}>
      <div>
        {stages.map((stage, index) => (
          <i key={stage} className={index < value ? "filled" : ""} />
        ))}
      </div>
      <span>{label}</span>
    </div>
  );
}
function PersonAvatar({ name, fallback }: { name: string; fallback: string }) {
  const src = personAvatars[name];
  return (
    <span className={`avatar avatar-${fallback}`}>
      {src ? <Image src={src} alt="" width={64} height={64} /> : fallback}
    </span>
  );
}
function OrchestratorAvatar() {
  return (
    <span className="activityAgent">
      <Image src={botAvatars.orchestrator} alt="" width={64} height={64} />
    </span>
  );
}

function duePresentation(apiCase: ApiCase): Pick<CaseSummary, "due" | "dueTone"> {
  if (apiCase.status === "CLOSED") return { due: "已完成", dueTone: "muted" };
  const value = apiCase.business_payload?.commitment_due_date;
  if (!value) return { due: "待确认", dueTone: "normal" };
  const dueDate = new Date(`${value}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return { due: formatDay(dueDate.toISOString()), dueTone: dueDate < today ? "danger" : "normal" };
}

function attentionFor(apiCase: ApiCase): string | undefined {
  if (apiCase.status === "CLOSED") return undefined;
  if (apiCase.phase === "INTAKE") return "等待 Case Owner 启动处置";
  if (apiCase.phase === "MANIFEST_REVIEW") return "等待 Case Owner 审批 Manifest";
  if (apiCase.phase === "PATH_EXPLORATION") return "等待 Path 探索完成";
  if (apiCase.phase === "PROFESSIONAL_COMMITMENT") {
    const pending =
      apiCase.commitment_nodes?.filter(
        (node) => node.status === "PENDING" || node.status === "BLOCKED",
      ).length ?? 0;
    return pending > 0 ? `${pending} 项专业承诺待完成` : "等待专业承诺汇合";
  }
  return "等待 Case Owner 最终决策";
}

function mapCase(apiCase: ApiCase): CaseSummary {
  const status: Record<ApiCase["status"], CaseStatus> = {
    OPEN: "处理中",
    CLOSED: "已关闭",
  };
  const phases: Record<ApiCase["phase"], { value: number; label: string }> = {
    INTAKE: { value: 1, label: "Case 受理" },
    MANIFEST_REVIEW: { value: 2, label: "Manifest 评审" },
    PATH_EXPLORATION: { value: 3, label: "Path 探索" },
    PROFESSIONAL_COMMITMENT: { value: 4, label: "专业承诺" },
    FINAL_REVIEW: { value: 5, label: "最终决策" },
  };
  const currentPhase =
    apiCase.status === "CLOSED" ? { value: 5, label: "最终决策" } : phases[apiCase.phase];
  const risk: Record<"HIGH" | "MEDIUM" | "LOW", CaseRisk> = { HIGH: "高", MEDIUM: "中", LOW: "低" };
  return {
    id: apiCase.id,
    title: apiCase.title,
    description: apiCase.description,
    status: status[apiCase.status],
    risk: risk[apiCase.business_payload?.risk_level ?? "MEDIUM"],
    attention: attentionFor(apiCase),
    ...duePresentation(apiCase),
    owner: apiCase.owner,
    ownerRole: apiCase.owner_role,
    ownerInitial: apiCase.owner.slice(0, 1),
    customer: apiCase.business_payload?.customer ?? "内部协同",
    updated: formatDayTime(apiCase.updated_at),
    phase: currentPhase.value,
    phaseLabel: currentPhase.label,
  };
}

export default function Home() {
  const [activeFilter, setActiveFilter] = useState<(typeof filters)[number]>("全部");
  const [search, setSearch] = useState("");
  const [selectedCase, setSelectedCase] = useState<CaseSummary | null>(null);
  const { identity } = useDemoIdentity();
  const [caseData, setCaseData] = useState<CaseSummary[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const visibleCases = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return caseData.filter(
      (item) =>
        (activeFilter === "全部" || item.status === activeFilter) &&
        (!keyword ||
          [item.id, item.title, item.customer, item.owner].some((value) =>
            value.toLowerCase().includes(keyword),
          )),
    );
  }, [activeFilter, search, caseData]);
  const openCount = caseData.filter((item) => item.status === "处理中").length;
  const attentionCases = caseData.filter((item) => item.attention);
  const overdueCount = attentionCases.filter((item) => item.dueTone === "danger").length;
  const closedCount = caseData.filter((item) => item.status === "已关闭").length;

  useEffect(() => {
    const controller = new AbortController();
    const loadCases = () =>
      apiGet<ApiCase[]>("/api/cases", undefined, controller.signal)
        .then((cases) => {
          setCaseData(cases.map(mapCase));
          setLoadState("ready");
        })
        .catch((error) => {
          if (isAbort(error)) return;
          setLoadState("error");
        });
    void loadCases();
    window.addEventListener("focus", loadCases);
    return () => {
      controller.abort();
      window.removeEventListener("focus", loadCases);
    };
  }, []);

  return (
    <div className="appShell">
      <AppSidebar active="overview" />

      <main className="mainArea">
        <header className="topbar">
          <div className="breadcrumb">
            <span>运营控制台</span>
            <b>/</b>Case 总览
          </div>
          <div className="topActions">
            <label className="globalSearch">
              <HomeIcon name="search" />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索 Case、客户或负责人"
                aria-label="搜索 Case"
              />
              <kbd>⌘ K</kbd>
            </label>
            <button className="iconButton" type="button" aria-label="通知">
              <HomeIcon name="bell" /><i />
            </button>
            <button className="createButton" type="button">
              <HomeIcon name="plus" />新建 Case
            </button>
          </div>
        </header>
        <div className="pageContent">
          <section className="welcome">
            <div>
              <p className="eyebrow">CASE OPERATIONS · LIVE</p>
              <h1>早上好，{identity.name}</h1>
              <p className="welcomeCopy">
                当前有 <strong>{attentionCases.length} 个事项</strong>需要你的判断，其中{" "}
                {overdueCount} 个已超过承诺期限。
              </p>
            </div>
            <div className="governanceNote">
              <span>Human governed</span>
              <p>Agent 提案 · 人员决策 · 全程留痕</p>
            </div>
          </section>
          <section className="metrics" aria-label="Case 指标">
            <article>
              <div className="metricIcon metricTeal"><HomeIcon name="active" /></div>
              <div>
                <span>进行中 Case</span>
                <strong>{openCount}</strong>
                <small>
                  <b>实时</b> 来自 Case API
                </small>
              </div>
            </article>
            <article>
              <div className="metricIcon metricAmber"><HomeIcon name="attention" /></div>
              <div>
                <span>需要关注</span>
                <strong>{attentionCases.length}</strong>
                <small>{overdueCount} 个已逾期</small>
              </div>
            </article>
            <article>
              <div className="metricIcon metricBlue"><HomeIcon name="check" /></div>
              <div>
                <span>已闭环 Case</span>
                <strong>{closedCount}</strong>
                <small>来自 Case API</small>
              </div>
            </article>
            <article>
              <div className="metricIcon metricViolet"><HomeIcon name="cases" /></div>
              <div>
                <span>全部 Case</span>
                <strong>{caseData.length}</strong>
                <small>当前数据集</small>
              </div>
            </article>
          </section>
          <div className="dashboardGrid">
            <section className="casePanel" id="case-overview">
              <div className="panelHeader">
                <div>
                  <h2>Case 总览</h2>
                  <p>跨组织异常处置的当前状态</p>
                </div>
                <button type="button">
                  查看全部 <HomeIcon name="arrow" />
                </button>
              </div>
              {loadState === "error" && (
                <div className="caseSyncNotice" role="alert">
                  Case 状态同步失败，当前列表可能不是最新。
                </div>
              )}
              <div className="caseToolbar">
                <div className="filterTabs" role="tablist" aria-label="按状态筛选">
                  {filters.map((filter) => (
                    <button
                      key={filter}
                      type="button"
                      role="tab"
                      aria-selected={activeFilter === filter}
                      className={activeFilter === filter ? "active" : ""}
                      onClick={() => setActiveFilter(filter)}
                    >
                      {filter}
                      {filter === "全部" && <span>{caseData.length}</span>}
                    </button>
                  ))}
                </div>
                <label className="tableSearch">
                  <HomeIcon name="search" />
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="筛选当前列表"
                    aria-label="筛选当前 Case 列表"
                  />
                </label>
              </div>
              <div className="caseTableWrap">
                <table className="caseTable">
                  <thead>
                    <tr>
                      <th>CASE</th>
                      <th>状态 / 风险</th>
                      <th>当前阶段</th>
                      <th>负责人</th>
                      <th>承诺期限</th>
                      <th>最近更新</th>
                      <th>
                        <span className="srOnly">操作</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleCases.map((item) => {
                      const hasWorkspace = item.id === "CM-2026-014";
                      const title = (
                        <>
                          <PhaseRing value={item.phase} label={item.phaseLabel} closed={item.status === "已关闭"} />
                          <span>
                            <b>{item.title}</b>
                            <small>
                              {item.id} · {item.customer}
                            </small>
                          </span>
                        </>
                      );
                      return (
                        <tr key={item.id}>
                          <td>
                            {hasWorkspace ? (
                              <a
                                className="caseTitle"
                                href={`/cases/${item.id}`}
                                style={{ color: "inherit", textDecoration: "none" }}
                              >
                                {title}
                              </a>
                            ) : (
                              <div className="caseTitle">{title}</div>
                            )}
                          </td>
                          <td>
                            <StatusPill status={item.status} />
                            <RiskMark risk={item.risk} />
                          </td>
                          <td>
                            <StageProgress value={item.phase} label={item.phaseLabel} />
                          </td>
                          <td>
                            <div className="ownerCell">
                              <PersonAvatar name={item.owner} fallback={item.ownerInitial} />
                              <span>
                                <b>{item.owner}</b>
                                <small>{item.ownerRole}</small>
                              </span>
                            </div>
                          </td>
                          <td>
                            <span className={`due due-${item.dueTone}`}>{item.due}</span>
                          </td>
                          <td>
                            <span className="updated">{item.updated}</span>
                          </td>
                          <td>
                            {hasWorkspace ? (
                              <a
                                className="rowAction"
                                href={`/cases/${item.id}`}
                                style={{
                                  display: "grid",
                                  placeItems: "center",
                                  textDecoration: "none",
                                }}
                                aria-label={`打开 ${item.title}`}
                              >
                                <HomeIcon name="right" />
                              </a>
                            ) : (
                              <button
                                className="rowAction"
                                type="button"
                                onClick={() => setSelectedCase(item)}
                                aria-label={`查看 ${item.title}`}
                              >
                                <HomeIcon name="right" />
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {visibleCases.length === 0 && (
                  <div className="emptyState">
                    <HomeIcon name="search" />
                    <strong>
                      {loadState === "loading" ? "正在同步 Case 状态" : "没有匹配的 Case"}
                    </strong>
                    <p>
                      {loadState === "loading"
                        ? "状态与阶段以 Case API 为准"
                        : "尝试调整状态或搜索关键词"}
                    </p>
                  </div>
                )}
              </div>
              <div className="tableFooter">
                <span>
                  显示 {visibleCases.length} / {caseData.length} 个 Case
                </span>
                <div>
                  <button type="button" disabled>
                    <HomeIcon name="left" />
                  </button>
                  <button type="button" className="active">
                    1
                  </button>
                  <button type="button" disabled>
                    <HomeIcon name="right" />
                  </button>
                </div>
              </div>
            </section>
            <aside className="rightRail">
              <section className="activityCard" id="activity">
                <div className="railHeader">
                  <div>
                    <h2>最新协作动态</h2>
                  </div>
                  <button type="button">全部</button>
                </div>
                <ol className="activityList">
                  <li>
                    <PersonAvatar name="王淼" fallback="王" />
                    <div>
                      <p>
                        <b>王淼</b> 提交了供应可行性承诺
                      </p>
                      <small>
                        <b>CM-2026-014</b>
                        <time>12 分钟前</time>
                      </small>
                    </div>
                  </li>
                  <li>
                    <OrchestratorAvatar />
                    <div>
                      <p>
                        <b>Orchestrator</b> 生成 Manifest v2
                      </p>
                      <small>
                        <b>CM-2026-012</b>
                        <time>28 分钟前</time>
                      </small>
                    </div>
                  </li>
                  <li>
                    <PersonAvatar name="林乔" fallback="林" />
                    <div>
                      <p>
                        <b>林乔</b> 请求补充技术证据
                      </p>
                      <small>
                        <b>CM-2026-015</b>
                        <time>1 小时前</time>
                      </small>
                    </div>
                  </li>
                  <li>
                    <span className="activityDone"><HomeIcon name="check" /></span>
                    <div>
                      <p>
                        <b>CM-2026-006</b> 已完成验证
                      </p>
                      <small>
                        <b>Case 日志</b>
                        <time>2 天前</time>
                      </small>
                    </div>
                  </li>
                </ol>
              </section>
            </aside>
          </div>
        </div>
      </main>
      {selectedCase && (
        <div className="drawerBackdrop">
          <button
            hidden
            type="button"
            onClick={() => setSelectedCase(null)}
            aria-label="关闭快速查看"
          />
          <aside
            className="caseDrawer"
            role="dialog"
            aria-modal="true"
            aria-label={`${selectedCase.title} 快速查看`}
          >
            <header>
              <div>
                <small>{selectedCase.id}</small>
                <h2>{selectedCase.title}</h2>
              </div>
              <button type="button" onClick={() => setSelectedCase(null)} aria-label="关闭">
                ×
              </button>
            </header>
            <div className="drawerBody">
              <div className="drawerBadges">
                <StatusPill status={selectedCase.status} />
                <RiskMark risk={selectedCase.risk} />
              </div>
              <p className="drawerDescription">{selectedCase.description}</p>
              <dl>
                <div>
                  <dt>当前阶段</dt>
                  <dd>{selectedCase.phaseLabel}</dd>
                </div>
                <div>
                  <dt>Case Owner</dt>
                  <dd>
                    {selectedCase.owner} · {selectedCase.ownerRole}
                  </dd>
                </div>
                <div>
                  <dt>业务对象</dt>
                  <dd>{selectedCase.customer}</dd>
                </div>
                <div>
                  <dt>承诺期限</dt>
                  <dd className={`due-${selectedCase.dueTone}`}>{selectedCase.due}</dd>
                </div>
              </dl>
              <div className="drawerStage">
                <span>处置进度</span>
                <StageProgress value={selectedCase.phase} label={selectedCase.phaseLabel} />
              </div>
              {selectedCase.attention && (
                <div className="drawerNotice">
                  <span>!</span>
                  <div>
                    <strong>待处理</strong>
                    <p>{selectedCase.attention}</p>
                  </div>
                </div>
              )}
            </div>
            <footer>
              <button
                type="button"
                className="secondaryButton"
                onClick={() => setSelectedCase(null)}
              >
                返回总览
              </button>
              <button type="button" className="createButton">
                打开 Case 工作台 <span>→</span>
              </button>
            </footer>
          </aside>
        </div>
      )}
    </div>
  );
}
