"use client";

import { useId, useState } from "react";
import type { CommitmentDecision } from "./lib/case";
import "./human-input.css";

export function CommitmentDecisionForm({
  revision,
  busy,
  onDecide,
}: {
  revision: number | null;
  busy: boolean;
  onDecide: (decision: CommitmentDecision, reason: string) => Promise<void>;
}) {
  const fieldId = useId();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  async function submit(decision: CommitmentDecision) {
    setError("");
    try {
      await onDecide(decision, reason.trim());
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "提交失败，请重试。");
    }
  }

  return (
    <section className="humanDecisionForm" aria-label="专业承诺决策">
      <strong>本次审批：方案 {revision === null ? "版本不可用" : `v${revision}`}</strong>
      <label className="humanInputField" htmlFor={fieldId}>
        决策理由
        <textarea
          id={fieldId}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="说明需要修改或否决的具体原因。"
          rows={3}
          disabled={busy}
        />
      </label>
      <small>修改或否决须填写理由；仅审批当前版本。</small>
      {error && (
        <p className="humanInputError" role="alert">
          {error}
        </p>
      )}
      <div className="humanInputActions">
        <button
          type="button"
          className="approve"
          disabled={busy || revision === null}
          onClick={() => void submit("APPROVE")}
        >
          通过
        </button>
        <button
          type="button"
          className="revise"
          disabled={busy || revision === null || !reason.trim()}
          onClick={() => void submit("REVISE")}
        >
          要求修改
        </button>
        <button
          type="button"
          className="reject"
          disabled={busy || revision === null || !reason.trim()}
          onClick={() => void submit("REJECT")}
        >
          否决
        </button>
      </div>
    </section>
  );
}

export function InformationAnswerForm({
  busy,
  onAnswer,
  request,
}: {
  busy: boolean;
  onAnswer: (answer: string, quantity?: number) => Promise<void>;
  request?: { material_id?: string | null; required_by?: string | null };
}) {
  const fieldId = useId();
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [quantity, setQuantity] = useState("");
  const isSupplyQuestion = Boolean(request?.material_id && request.required_by);
  const numericQuantity = quantity.trim() === "" ? undefined : Number(quantity);
  const validQuantity = numericQuantity !== undefined && Number.isSafeInteger(numericQuantity) && numericQuantity >= 0;

  async function submit() {
    setError("");
    try {
      await onAnswer(answer.trim(), isSupplyQuestion ? numericQuantity : undefined);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "回答提交失败，请重试。");
    }
  }

  return (
    <section className="humanAnswerForm" aria-label="回答 Agent 的信息请求">
      {isSupplyQuestion && (
        <>
          <strong>{request?.material_id} · {request?.required_by} 前</strong>
          <label className="humanInputField" htmlFor={`${fieldId}-quantity`}>
            可供货数量（件）
            <input
              id={`${fieldId}-quantity`}
              type="number"
              min="0"
              step="1"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              placeholder="无法供货时填写 0"
              disabled={busy}
            />
          </label>
        </>
      )}
      <label className="humanInputField" htmlFor={fieldId}>
        {isSupplyQuestion ? "确认依据" : "补充信息"}
        <textarea
          id={fieldId}
          value={answer}
          onChange={(event) => setAnswer(event.target.value)}
          placeholder={isSupplyQuestion ? "说明供应来源、可到货日期及确认依据，例如供应商书面回复。" : "提供已确认的信息、来源或仍然无法确认的情况。"}
          rows={4}
          disabled={busy}
        />
      </label>
      {error && (
        <p className="humanInputError" role="alert">
          {error}
        </p>
      )}
      <div className="humanInputActions">
        <button
          type="button"
          className="approve"
          disabled={busy || !answer.trim() || (isSupplyQuestion && !validQuantity)}
          onClick={() => void submit()}
        >
          提交补充信息
        </button>
      </div>
    </section>
  );
}
