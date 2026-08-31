"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import AppSidebar from "../app-sidebar";
import { apiGet, apiPost, isAbort } from "../lib/api";
import {
  commitmentCopy,
  type ApprovalContext,
  type CommitmentDecision,
  type CommitmentNode,
} from "../lib/case";
import { demoIdentities } from "../lib/identities";
import "./inbox.css";

type InboxItem = {
  case_id: string;
  case_title: string;
  path_id: string;
  path_title: string;
  node: CommitmentNode;
  approval_context: ApprovalContext;
};

export default function InboxPage() {
  const [identityIndex, setIdentityIndex] = useState(0);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [reviewItem, setReviewItem] = useState<InboxItem | null>(null);
  const currentIdentity = demoIdentities[identityIndex];

  useEffect(() => {
    const controller = new AbortController();
    apiGet<InboxItem[]>("/api/inbox", { role: currentIdentity.role }, controller.signal)
      .then((data) => {
        setItems(data);
        setLoadState("ready");
      })
      .catch((error) => {
        if (isAbort(error)) return;
        setItems([]);
        setLoadState("error");
      });
    return () => controller.abort();
  }, [currentIdentity.role]);

  function selectIdentity(nextIdentityIndex: number) {
    setItems([]);
    setLoadState("loading");
    setMessage("");
    setReviewItem(null);
    setIdentityIndex(nextIdentityIndex);
  }

  async function decide(item: InboxItem, decision: CommitmentDecision) {
    const itemKey = `${item.case_id}-${item.path_id}-${item.node.id}`;
    setBusyKey(itemKey);
    setMessage("");
    try {
      await apiPost(
        `/api/cases/${item.case_id}/paths/${item.node.path_id}/commitments/${item.node.id}/decision`,
        { actor: currentIdentity.name, role: currentIdentity.role, decision },
      );
      const nextItems = await apiGet<InboxItem[]>("/api/inbox", { role: currentIdentity.role });
      setItems(nextItems);
      setReviewItem(null);
      const result = decision === "APPROVE" ? "通过" : decision === "REVISE" ? "要求修改" : "否决";
      setMessage(`${currentIdentity.name} 已${result} ${item.case_id} 的 ${item.node.id} 节点。`);
    } catch {
      setMessage("审批操作失败：请确认当前身份、节点状态与本地 API。");
    } finally {
      setBusyKey(null);
    }
  }

  function approvalActions(item: InboxItem) {
    if (item.node.status !== "PENDING" || item.node.role !== currentIdentity.role) return null;
    const itemKey = `${item.case_id}-${item.path_id}-${item.node.id}`;
    const busy = busyKey === itemKey;
    return (
      <div className="inboxApprovalActions" aria-label={`${item.node.id} 审批操作`}>
        <button className="approve" disabled={busy} onClick={() => decide(item, "APPROVE")}>通过</button>
        <button className="revise" disabled={busy} onClick={() => decide(item, "REVISE")}>修改</button>
        <button className="reject" disabled={busy} onClick={() => decide(item, "REJECT")}>否决</button>
      </div>
    );
  }

  return (
    <div className="appShell">
      <AppSidebar
        active="inbox"
        identity={currentIdentity}
        identities={demoIdentities}
        inboxCount={loadState === "ready" ? items.length : undefined}
        busy={busyKey !== null}
        onIdentitySelect={selectIdentity}
      />

      <main className="mainArea">
        <header className="topbar">
          <div className="breadcrumb"><span>运营控制台</span><b>/</b>我的待办</div>
          <div className="inboxIdentity"><span>{currentIdentity.name}</span><strong>{currentIdentity.role}</strong></div>
        </header>
        <div className="inboxPage">
          <header className="inboxHero">
            <div><p className="eyebrow">ROLE-SCOPED APPROVALS</p><h1>我的待办</h1><p>汇总所有 Case 中分配给当前角色、且依赖已经满足的待审批节点。</p></div>
            <div className="inboxCount"><strong>{loadState === "ready" ? items.length : "—"}</strong><span>待本人审批</span></div>
          </header>

          {message && <div className="inboxMessage" role="status">{message}</div>}
          {loadState === "loading" && <div className="inboxState"><strong>正在同步待审批节点</strong><p>审批数据来自跨 Case Inbox API。</p></div>}
          {loadState === "error" && <div className="inboxState error" role="alert"><strong>待办同步失败</strong><p>请确认本地 API 已启动后重试。</p></div>}
          {loadState === "ready" && items.length === 0 && <div className="inboxState"><strong>当前没有待批准事项</strong><p>可从左下角切换演示身份，查看其他角色的审批节点。</p></div>}

          {loadState === "ready" && items.length > 0 && (
            <section className="inboxGrid" aria-label={`${currentIdentity.role} 待审批节点`}>
              {items.map((item) => (
                <article className="inboxItem" key={`${item.case_id}-${item.path_id}-${item.node.id}`}>
                  <header><span>PENDING</span><small>{item.path_id} · {item.node.id}</small></header>
                  <h2>{commitmentCopy[item.node.id] ?? item.node.review_dimension}</h2>
                  <p>{item.path_title}</p>
                  <dl><div><dt>Case</dt><dd><Link href={`/cases/${item.case_id}`}>{item.case_id} · {item.case_title}</Link></dd></div><div><dt>责任角色</dt><dd>{item.node.role}</dd></div></dl>
                  <button className="reviewEvidence" type="button" onClick={() => setReviewItem(item)}>查看审批依据 →</button>
                  {approvalActions(item)}
                </article>
              ))}
            </section>
          )}
        </div>
      </main>

      {reviewItem && (
        <div className="inboxReviewBackdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setReviewItem(null); }}>
          <aside className="inboxReviewPanel" role="dialog" aria-modal="true" aria-label={`${reviewItem.node.role} 审批依据`}>
            <header><div><small>ROLE-SCOPED EVIDENCE · {reviewItem.node.id}</small><h2>{reviewItem.node.role}审批依据</h2><p>{reviewItem.case_id} · {reviewItem.path_title}</p></div><button aria-label="关闭审批依据" onClick={() => setReviewItem(null)}>×</button></header>
            <div className="inboxReviewBody">
              <section><small>本次责任边界</small><strong>{commitmentCopy[reviewItem.node.id] ?? reviewItem.node.review_dimension}</strong><p>你只批准本节点对应的专业判断，不代表其他角色，也不执行任何业务动作。</p></section>
              <section className="roleEvidence"><small>你的专业判断与证据摘要</small><strong>{reviewItem.approval_context.role_report?.dimension ?? "对应角色报告尚未生成"}</strong><p>{reviewItem.approval_context.role_report?.report ?? "当前没有可供本角色审查的报告，请选择“修改”要求补充。"}</p></section>
              <section><small>推荐方案 · REVISION {reviewItem.approval_context.revision ?? "—"}</small><div className="inboxRecommendation"><strong>Agent 建议（非业务决定）</strong><p>{reviewItem.approval_context.recommendation || "暂无推荐方案。"}</p></div></section>
            </div>
            <footer><span><small>当前身份</small><strong>{currentIdentity.name} · {currentIdentity.role}</strong></span>{approvalActions(reviewItem)}</footer>
          </aside>
        </div>
      )}
    </div>
  );
}
