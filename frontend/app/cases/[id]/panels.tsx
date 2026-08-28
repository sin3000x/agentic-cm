import Image from "next/image";
import { botAvatars, personAvatars } from "../../lib/identities";
import { formatThreadTime } from "../../lib/format";
import {
  aiRunCopy,
  pathIdForRun,
  type AgentRun,
  type AiRunKind,
  type CapabilityDetails,
  type ManifestPath,
  type PathExecutionMode,
  type PathRunUiStatus,
} from "../../lib/case";

export function PersonIcon({ name, fallback, className }: { name?: string; fallback: string; className: string }) {
  const src = name ? personAvatars[name] : undefined;
  return <span className={className}>{src ? <Image src={src} alt="" width={80} height={80} /> : fallback}</span>;
}

export function BotIcon({ kind, className }: { kind: keyof typeof botAvatars; className: string }) {
  return <span className={className}><Image src={botAvatars[kind]} alt="" width={80} height={80} /></span>;
}

export function AiWorkingCard({
  kind,
  step,
  runs,
  paths = [],
  executionMode = "parallel",
  maxConcurrency = 4,
}: {
  kind: AiRunKind;
  step: number;
  runs: AgentRun[];
  paths?: ManifestPath[];
  executionMode?: PathExecutionMode;
  maxConcurrency?: number;
}) {
  const copy = aiRunCopy[kind];
  const agentType = kind === "manifest" ? "orchestrator" : kind === "alternatives" ? "path" : "synthesis";
  const pathRunStates = paths.map((path) => {
    const run = runs.find((item) => pathIdForRun(item) === path.id);
    return { path, run, status: (run?.status ?? "QUEUED") as PathRunUiStatus };
  });
  const completedPathCount = pathRunStates.filter((item) => item.status === "SUCCEEDED").length;
  const runningPathCount = pathRunStates.filter((item) => item.status === "RUNNING").length;
  const runningPathIndex = pathRunStates.findIndex((item) => item.status === "RUNNING");
  return (
    <section className="aiWorkingCard" aria-live="polite" aria-label={copy.title}>
      <div className="aiOrb" aria-hidden="true"><i /><i /><b>AI</b></div>
      <div className="aiWorkingBody">
        <small>{copy.eyebrow}</small>
        <h3>{kind === "alternatives" ? `正在${executionMode === "parallel" ? "并行" : "逐条"}推演 ${paths.length} 条 Path` : copy.title}<span className="thinkingDots"><i /><i /><i /></span></h3>
        {kind === "alternatives" ? (
          <>
            <div className="pathRunSummary">
              <span><small>执行方式</small><strong>{executionMode === "parallel" ? `并行执行 · 最多 ${Math.min(paths.length, maxConcurrency)} 条` : "串行队列 · 同一时间 1 条"}</strong></span>
              <span><small>整体进度</small><strong>{completedPathCount} / {paths.length} 条已完成</strong></span>
              <span><small>{executionMode === "parallel" ? "当前并发" : "当前位置"}</small><strong>{executionMode === "parallel" ? `${runningPathCount} 条运行中` : runningPathIndex >= 0 ? `第 ${runningPathIndex + 1} / ${paths.length} 条` : "正在建立运行记录"}</strong></span>
            </div>
            <ol className="pathRunQueue" aria-label={`Path Agent ${executionMode === "parallel" ? "并行执行" : "串行执行"}状态`}>
              {pathRunStates.map(({ path, run, status }, index) => {
                const latestEvent = run?.events.at(-1);
                const statusLabel = status === "RUNNING" ? "正在推演" : status === "SUCCEEDED" ? "已完成" : status === "FAILED" ? "失败" : executionMode === "parallel" ? "启动中" : "排队中";
                return (
                  <li className={status.toLowerCase()} key={path.id}>
                    <span className="pathRunIndex">{status === "SUCCEEDED" ? "✓" : String(index + 1).padStart(2, "0")}</span>
                    <div><strong>{path.title}</strong><small>{latestEvent ? `${latestEvent.summary} · 已记录 ${run?.events.length ?? 0} 步` : status === "QUEUED" ? executionMode === "parallel" ? "正在启动并行运行" : "等待上一条 Path 完成" : "正在启动 Path Agent"}</small></div>
                    <b>{statusLabel}</b>
                  </li>
                );
              })}
            </ol>
          </>
        ) : (
          <>
            <div className="aiStepTrack">
              {copy.steps.map((item, index) => (
                <span className={index < step ? "done" : index === step ? "active" : ""} key={item}>
                  <i>{index < step ? "✓" : index + 1}</i>{item}
                </span>
              ))}
            </div>
            <div className="aiProgress"><i style={{ width: `${Math.min(92, 18 + step * 24)}%` }} /></div>
          </>
        )}
        <p>你可以留在当前页面，结果完成后会自动出现；AI 只生成建议，不会替人批准业务承诺。</p>
        <details className="embeddedLiveTrace" open>
          <summary><span><small>LIVE TRACE</small><strong>实时审计轨迹</strong></span><em>每 600ms 刷新</em></summary>
          <AgentTracePanel runs={runs} agentType={agentType} autoExpand />
        </details>
      </div>
    </section>
  );
}

export function CapabilityPanel({ details }: { details: CapabilityDetails }) {
  const groups = [
    { key: "policies" as const, label: "POLICY · 强制责任", note: "由平台结构化匹配并编译为 CommitmentDAG 责任节点" },
    { key: "skills" as const, label: "SKILL · 认知方法", note: "由 Agent Adapter 使用，不能代替业务审批" },
    { key: "knowledge" as const, label: "KNOWLEDGE · 建议材料", note: "带来源的历史观察，不是当前 Case 事实" },
  ];
  return (
    <section className="capabilityPanel" aria-label="Manifest 能力快照">
      <div className="capabilityHeader">
        <span><strong>能力快照</strong><small>{details.snapshot_status === "frozen" ? "已随 Manifest 冻结" : "当前预览"}</small></span>
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
                <p>{asset.description ?? asset.content?.summary ?? asset.instructions?.[0] ?? `${asset.requirements?.commitments?.length ?? 0} 个强制责任节点`}</p>
              </article>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

export function ManifestYamlPanel({ yaml, downloadHref, onCopy }: { yaml: string; downloadHref: string; onCopy: () => void }) {
  return (
    <section className="manifestYamlPanel" aria-label="完整 Manifest YAML">
      <header>
        <span><strong>完整 Manifest YAML</strong><small>全局 Knowledge 与所有 Path 的 Skill / Policy / Knowledge</small></span>
        <span>
          <button className="linkButton" onClick={onCopy}>复制 YAML</button>
          <a className="linkButton" href={downloadHref} download>下载 YAML</a>
        </span>
      </header>
      <pre>{yaml}</pre>
    </section>
  );
}

export function AgentTracePanel({ runs, agentType, autoExpand = false }: { runs: AgentRun[]; agentType: "orchestrator" | "path" | "synthesis"; autoExpand?: boolean }) {
  const label = agentType === "orchestrator" ? "ORCHESTRATOR" : agentType === "path" ? "PATH AGENT" : "SYNTHESIS AGENT";
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
        <details className={`traceRun ${run.status.toLowerCase()}`} open={autoExpand && (run.status === "RUNNING" || run.status === "FAILED")} key={run.id}>
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
                      <summary>{typeof event.details.manifest_yaml === "string" ? "查看完整 Manifest YAML" : "查看输入 / 输出详情"}</summary>
                      {typeof event.details.manifest_yaml === "string" ? (
                        <pre>{event.details.manifest_yaml}</pre>
                      ) : (
                        <pre>{JSON.stringify(event.details, null, 2)}</pre>
                      )}
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
