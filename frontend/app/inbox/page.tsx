"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import AppSidebar from "../app-sidebar";
import { CommitmentDecisionForm, InformationAnswerForm } from "../human-input";
import { apiGet, apiPost, isAbort } from "../lib/api";
import {
  commitmentCopy,
  type CommitmentDecision,
  type CommitmentInboxItem,
  type InformationInboxItem,
  type InboxItem,
} from "../lib/case";
import { useDemoIdentity } from "../lib/identities";
import "./inbox.css";

function itemKey(item: InboxItem) {
  return `${item.case_id}-${item.path_id}-${item.kind}-${item.kind === "commitment" ? item.node.id : item.information_request.id}`;
}

function itemRole(item: InboxItem) {
  return item.kind === "commitment" ? item.node.role : item.information_request.role;
}

export default function InboxPage() {
  const { identity: currentIdentity } = useDemoIdentity();
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [reviewItem, setReviewItem] = useState<InboxItem | null>(null);

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

  function selectIdentity() {
    setItems([]);
    setLoadState("loading");
    setMessage("");
    setReviewItem(null);
  }

  async function finishItem(item: InboxItem, result: string) {
    setItems((current) => current.filter((candidate) => itemKey(candidate) !== itemKey(item)));
    setReviewItem(null);
    setMessage(result);
    try {
      setItems(await apiGet<InboxItem[]>("/api/inbox", { role: currentIdentity.role }));
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }

  async function decide(item: CommitmentInboxItem, decision: CommitmentDecision, reason: string) {
    const revision = item.approval_context.revision;
    if (revision === null) throw new Error("未获取到审批版本，请重新打开审批依据。");
    setBusyKey(itemKey(item));
    setMessage("");
    try {
      await apiPost(
        `/api/cases/${item.case_id}/paths/${item.path_id}/commitments/${item.node.id}/decision`,
        {
          actor: currentIdentity.name,
          role: currentIdentity.role,
          decision,
          expected_revision: revision,
          reason,
        },
      );
      const result = decision === "APPROVE" ? "通过" : decision === "REVISE" ? "要求修改" : "否决";
      await finishItem(
        item,
        `${currentIdentity.name} 已${result} ${item.case_id} 的方案 v${revision}。`,
      );
    } finally {
      setBusyKey(null);
    }
  }

  async function answer(item: InformationInboxItem, content: string) {
    setBusyKey(itemKey(item));
    setMessage("");
    try {
      await apiPost(
        `/api/cases/${item.case_id}/paths/${item.path_id}/information-requests/${item.information_request.id}/answer`,
        { actor: currentIdentity.name, role: currentIdentity.role, answer: content },
      );
      await finishItem(item, "补充信息已记录；全部问题回答后，由 Case Owner 继续 Path 推演。");
    } finally {
      setBusyKey(null);
    }
  }

  const approvalCount = items.filter((item) => item.kind === "commitment").length;
  const informationCount = items.length - approvalCount;

  return (
    <div className="appShell">
      <AppSidebar
        active="inbox"
        inboxCount={loadState === "ready" ? items.length : null}
        busy={busyKey !== null}
        onIdentitySelect={selectIdentity}
      />
      <main className="mainArea">
        <header className="topbar">
          <div className="breadcrumb">
            <span>运营控制台</span>
            <b>/</b>我的待办
          </div>
          <div className="inboxIdentity">
            <span>{currentIdentity.name}</span>
            <strong>{currentIdentity.role}</strong>
          </div>
        </header>
        <div className="inboxPage">
          <header className="inboxHero">
            <div>
              <p className="eyebrow">MY CASE ACTIONS</p>
              <h1>我的待办</h1>
              <p>处理分配给当前角色的专业审批和 Agent 信息请求。</p>
            </div>
            <div className="inboxCount">
              <strong>{loadState === "ready" ? items.length : "—"}</strong>
              <span>
                {approvalCount} 待审批 · {informationCount} 待补信息
              </span>
            </div>
          </header>
          {message && (
            <div className="inboxMessage" role="status">
              {message}
            </div>
          )}
          {loadState === "loading" && (
            <div className="inboxState">
              <strong>正在同步待办</strong>
              <p>读取当前角色的审批节点与信息请求。</p>
            </div>
          )}
          {loadState === "error" && (
            <div className="inboxState error" role="alert">
              <strong>待办同步失败</strong>
              <p>请确认本地 API 已启动后刷新重试。</p>
            </div>
          )}
          {loadState === "ready" && items.length === 0 && (
            <div className="inboxState">
              <strong>当前没有待处理事项</strong>
              <p>可从左下角切换演示身份，查看其他角色的待办。</p>
            </div>
          )}
          {loadState === "ready" && items.length > 0 && (
            <section className="inboxGrid" aria-label={`${currentIdentity.role} 待处理事项`}>
              {items.map((item) => (
                <article
                  className={`inboxItem ${item.kind === "information_request" ? "informationInboxItem" : ""}`}
                  key={itemKey(item)}
                >
                  <header>
                    <span>{item.kind === "commitment" ? "专业审批" : "补充信息"}</span>
                    <small>
                      {item.path_id}
                      {item.kind === "commitment" &&
                        ` · 方案 v${item.approval_context.revision ?? "—"}`}
                    </small>
                  </header>
                  <h2>
                    {item.kind === "commitment"
                      ? (commitmentCopy[item.node.id] ?? item.node.review_dimension)
                      : item.information_request.question}
                  </h2>
                  <p>{item.path_title}</p>
                  {item.kind === "information_request" && (
                    <p className="informationReason">{item.information_request.reason}</p>
                  )}
                  <dl>
                    <div>
                      <dt>Case</dt>
                      <dd>
                        <Link href={`/cases/${item.case_id}`}>
                          {item.case_id} · {item.case_title}
                        </Link>
                      </dd>
                    </div>
                    <div>
                      <dt>责任角色</dt>
                      <dd>{itemRole(item)}</dd>
                    </div>
                  </dl>
                  <button
                    className="reviewEvidence"
                    type="button"
                    onClick={() => setReviewItem(item)}
                  >
                    {item.kind === "commitment" ? "查看依据并处理 →" : "回答信息请求 →"}
                  </button>
                </article>
              ))}
            </section>
          )}
        </div>
      </main>
      {reviewItem && (
        <div
          className="inboxReviewBackdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && busyKey === null) setReviewItem(null);
          }}
        >
          <aside
            className="inboxReviewPanel"
            role="dialog"
            aria-modal="true"
            aria-label={`${itemRole(reviewItem)}${reviewItem.kind === "commitment" ? "审批依据" : "补充信息"}`}
          >
            <header>
              <div>
                <h2>
                  {itemRole(reviewItem)}
                  {reviewItem.kind === "commitment" ? "审批依据" : "补充信息"}
                </h2>
                <p>
                  {reviewItem.case_id} · {reviewItem.path_title}
                </p>
              </div>
              <button
                aria-label="关闭待办详情"
                disabled={busyKey !== null}
                onClick={() => setReviewItem(null)}
              >
                ×
              </button>
            </header>
            <div className="inboxReviewBody">
              {reviewItem.kind === "commitment" ? (
                <>
                  <section>
                    <small>审批事项 · 方案 v{reviewItem.approval_context.revision ?? "—"}</small>
                    <strong>
                      {commitmentCopy[reviewItem.node.id] ?? reviewItem.node.review_dimension}
                    </strong>
                  </section>
                  <section className="roleEvidence">
                    <small>审批依据</small>
                    <strong>
                      {reviewItem.approval_context.role_report?.dimension ?? "暂无审批依据"}
                    </strong>
                    <p>
                      {reviewItem.approval_context.role_report?.report ??
                        "暂无报告，请要求修改并说明需要补充的内容。"}
                    </p>
                  </section>
                  <section>
                    <small>Agent 推荐方案</small>
                    <p>{reviewItem.approval_context.recommendation || "暂无推荐方案。"}</p>
                  </section>
                  {reviewItem.node.status === "PENDING" &&
                    reviewItem.node.role === currentIdentity.role && (
                      <CommitmentDecisionForm
                        key={`${currentIdentity.name}-${itemKey(reviewItem)}-${reviewItem.approval_context.revision}`}
                        revision={reviewItem.approval_context.revision}
                        busy={busyKey !== null}
                        onDecide={(decision, reason) => decide(reviewItem, decision, reason)}
                      />
                    )}
                </>
              ) : (
                <>
                  <section className="roleEvidence">
                    <small>Path Agent 的问题</small>
                    <strong>{reviewItem.information_request.question}</strong>
                    <p>{reviewItem.information_request.reason}</p>
                  </section>
                  {reviewItem.information_request.role === currentIdentity.role && (
                    <InformationAnswerForm
                      key={`${currentIdentity.name}-${itemKey(reviewItem)}`}
                      busy={busyKey !== null}
                      onAnswer={(content) => answer(reviewItem, content)}
                    />
                  )}
                </>
              )}
            </div>
            <footer>
              <span>
                <small>当前身份</small>
                <strong>
                  {currentIdentity.name} · {currentIdentity.role}
                </strong>
              </span>
            </footer>
          </aside>
        </div>
      )}
    </div>
  );
}
