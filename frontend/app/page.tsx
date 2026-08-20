"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const cases = [
  { id: "CM-2026-014", title: "订单预计延期", status: "处理中", active: true },
  { id: "CM-2026-012", title: "供应商交付异常", status: "阻塞" },
  { id: "CM-2026-015", title: "替代料认证缺口", status: "待确认" },
  { id: "CM-2026-006", title: "华南仓到货差异", status: "已关闭" },
];

const stages = ["Case 受理", "Manifest 评审", "Path 探索", "最终决策"];

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
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [capabilities, setCapabilities] = useState<CapabilityDetails | null>(null);
  const [showCapabilities, setShowCapabilities] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/cases/CM-2026-014`)
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((data) => setApproved(data.phase === "PATH_EXPLORATION"))
      .catch(() => setMessage("API 尚未连接，当前展示固定演示数据。"));
  }, []);

  async function approveManifest() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/cases/CM-2026-014/manifest/approve`, { method: "POST" });
      if (!response.ok) throw new Error("approve failed");
      setApproved(true);
      setMessage("Manifest 已批准；主计划与研发评审已并行开放。 ");
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
      setCapabilities(null);
      setShowCapabilities(false);
      setMessage("Golden Path 演示数据已重置。 ");
    } catch {
      setMessage("重置失败：本地 API 未连接。 ");
    } finally {
      setBusy(false);
    }
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

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandMark">AC</span>
          <div><strong>Agentic CM</strong><small>Supply chain cases</small></div>
        </div>
        <nav aria-label="主要导航" className="nav">
          <a className="navItem active" href="#cases"><span>◇</span> Cases <b>5</b></a>
          <a className="navItem" href="#inbox"><span>□</span> 我的 Inbox <b>2</b></a>
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
          <span className="avatar">陈</span>
          <span><small>当前角色</small><strong>陈澄 · 订单履行经理</strong></span>
          <button aria-label="切换演示身份">⌄</button>
          <em>Demo identity simulation</em>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">Cases <span>/</span> CM-2026-014</div>
          <div className="topActions"><button className="ghost">审计记录</button><button className="ghost" disabled={busy} onClick={resetDemo}>重置 Demo</button></div>
        </header>
        <div className="content">
          <div className="caseHeader">
            <div>
              <div className="eyebrow"><span className="statusDot" /> OPEN <span>·</span> 高优先级</div>
              <h1>订单预计延期</h1>
              <p>订单 SO-48392 的关键物料预计晚于承诺日期 12 天，可能影响客户交付。</p>
            </div>
            <button className="primary">继续处理 <span>→</span></button>
          </div>
          <div className="metaRow">
            <div><small>CASE OWNER</small><strong>陈澄</strong><span>订单履行经理</span></div>
            <div><small>当前阶段</small><strong>{approved ? "Path 探索" : "Manifest 评审"}</strong><span>{approved ? "等待并行评审" : "等待 Owner 决策"}</span></div>
            <div><small>目标交付日</small><strong>2026-08-24</strong><span className="danger">预计延期 12 天</span></div>
            <div><small>最后更新</small><strong>今天 10:42</strong><span>Orchestrator</span></div>
          </div>
          <ol className="stageBar" aria-label="Case 当前进度">
            {stages.map((stage, index) => (
              <li className={index < (approved ? 3 : 2) ? "done" : ""} key={stage}>
                <span>{index < 1 ? "✓" : index + 1}</span><strong>{stage}</strong>
              </li>
            ))}
          </ol>
          <div className="mainGrid">
            <section className="panel manifest">
              {message && <div className="toast" role="status">{message}</div>}
              {approved ? (
                <>
                  <div className="panelTitle">
                    <div><span className="agentIcon">✓</span><span><small>PATH ATTEMPT · ATTEMPT-01</small><h2>物料替代 · 审批 DAG</h2></span></div>
                    <span className="version">AWAITING HUMAN</span>
                  </div>
                  <p className="lead">方案 v1 已覆盖候选物料 A / B。两个上游专业评审无相互依赖，现已并行开放。</p>
                  <div className="dag" aria-label="Commitment DAG">
                    <article className="dagNode ready"><span>READY</span><h3>主计划</h3><p>确认 A / B 供应可行性</p></article>
                    <article className="dagNode ready"><span>READY</span><h3>研发</h3><p>确认 A / B 技术可行性</p></article>
                    <div className="dagJoin"><i /><i /></div>
                    <article className="dagNode blocked"><span>BLOCKED</span><h3>一线经理</h3><p>等待供应与技术承诺</p></article>
                  </div>
                  <div className="metricStrip">
                    <span><strong>2</strong><small>parallel review branches</small></span>
                    <span><strong>0</strong><small>preserved commitments</small></span>
                    <span><strong>0</strong><small>re-review avoided</small></span>
                  </div>
                  <button className="linkButton capabilityToggle" onClick={toggleCapabilities}>{showCapabilities ? "收起能力快照 ↑" : "查看本次能力快照 →"}</button>
                  {showCapabilities && capabilities && <CapabilityPanel details={capabilities} />}
                </>
              ) : (
                <>
              <div className="panelTitle">
                <div><span className="agentIcon">✦</span><span><small>ORCHESTRATOR 建议</small><h2>审查 Path Manifest</h2></span></div>
                <span className="version">v1 · 待批准</span>
              </div>
              <p className="lead">结合当前 Case、强制 Policy 与历史 Experience，建议先探索一条最小可行路径。</p>
              <article className="pathCard">
                <div className="pathHeading"><span className="pathBadge">PATH 01</span><span className="recommended">推荐</span><button aria-label="移除该 Path">×</button></div>
                <h3>Material Substitution <span>物料替代</span></h3>
                <p>评估已经过预筛的替代物料 A / B，通过供应、技术与客户接受度的并行确认，形成可审查的交付建议。</p>
                <div className="pathStats">
                  <span><small>责任角色</small><strong>3</strong></span>
                  <span><small>并行评审分支</small><strong>2</strong></span>
                  <span><small>强制 Policy</small><strong>2</strong></span>
                  <span><small>历史 Experience</small><strong>1</strong></span>
                </div>
                <button className="linkButton" onClick={toggleCapabilities}>{showCapabilities ? "收起执行层 ↑" : "查看执行层与能力快照 →"}</button>
              </article>
              {showCapabilities && capabilities && <CapabilityPanel details={capabilities} />}
              <div className="approvalBox">
                <span><strong>批准范围</strong><small>批准 Decision Layer 中保留的全部 Path；不代表逐项审批底层 Skill 或 Tool。</small></span>
                <button className="primary" disabled={busy} onClick={approveManifest}>{busy ? "处理中…" : "批准并启动 Path"}</button>
              </div>
                </>
              )}
            </section>
            <aside className="rightRail">
              <section className="panel facts">
                <div className="compactTitle"><h2>Case 事实</h2><button>查看全部</button></div>
                <dl>
                  <div><dt>订单</dt><dd>SO-48392</dd></div>
                  <div><dt>客户</dt><dd>Northstar Mobility</dd></div>
                  <div><dt>关键物料</dt><dd>MCU-X7</dd></div>
                  <div><dt>缺口数量</dt><dd>18,400 pcs</dd></div>
                </dl>
              </section>
              <section className="panel proposal">
                <div className="compactTitle"><h2>Case Owner Proposal</h2><span>v1 · 创建时</span></div>
                <blockquote>“建议优先评估现有认证范围内的替代物料，避免直接承诺未经客户确认的新方案。”</blockquote>
                <p>陈澄 · 订单履行经理（Case Owner） <span>创建于今天 08:46</span></p>
              </section>
              <section className="notice"><strong>演示安全边界</strong><p>本 Demo 不连接或修改 ERP、库存、订单及客户系统；所有执行均为 sandbox 推演。</p></section>
            </aside>
          </div>
        </div>
      </section>
    </main>
  );
}
