import Image from "next/image";
import { botAvatars, personAvatars } from "../../lib/identities";
import { formatThreadTime } from "../../lib/format";
import {
  aiRunCopy,
  pathIdForRun,
  type AgentRun,
  type AgentTraceEvent,
  type AiRunKind,
  type CapabilityDetails,
  type ManifestPath,
  type PathExecutionMode,
  type PathRunUiStatus,
} from "../../lib/case";

export function PersonIcon({
  name,
  fallback,
  className,
}: {
  name?: string;
  fallback: string;
  className: string;
}) {
  const src = name ? personAvatars[name] : undefined;
  return (
    <span className={className}>
      {src ? <Image src={src} alt="" width={80} height={80} /> : fallback}
    </span>
  );
}

export function BotIcon({ kind, className }: { kind: keyof typeof botAvatars; className: string }) {
  return (
    <span className={className}>
      <Image src={botAvatars[kind].replace(".png", "-transparent.png")} alt="" width={80} height={80} />
    </span>
  );
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
  const agentType =
    kind === "manifest" ? "orchestrator" : kind === "alternatives" ? "path" : "synthesis";
  const pathRunStates = paths.map((path) => {
    const run = runs.find((item) => pathIdForRun(item) === path.id);
    return { path, run, status: (run?.status ?? "QUEUED") as PathRunUiStatus };
  });
  const completedPathCount = pathRunStates.filter((item) => item.status === "SUCCEEDED").length;
  const runningPathCount = pathRunStates.filter((item) => item.status === "RUNNING").length;
  const runningPathIndex = pathRunStates.findIndex((item) => item.status === "RUNNING");
  return (
    <section className="aiWorkingCard" aria-live="polite" aria-label={copy.title}>
      <div className="aiOrb" aria-hidden="true">
        <i />
        <i />
        <b>AI</b>
      </div>
      <div className="aiWorkingBody">
        <small>{copy.eyebrow}</small>
        <h3>
          {kind === "alternatives"
            ? `正在${executionMode === "parallel" ? "并行" : "逐条"}推演 ${paths.length} 条 Path`
            : copy.title}
          <span className="thinkingDots">
            <i />
            <i />
            <i />
          </span>
        </h3>
        {kind === "alternatives" ? (
          <>
            <div className="pathRunSummary">
              <span>
                <small>执行方式</small>
                <strong>
                  {executionMode === "parallel"
                    ? `并行执行 · 最多 ${Math.min(paths.length, maxConcurrency)} 条`
                    : "串行队列 · 同一时间 1 条"}
                </strong>
              </span>
              <span>
                <small>整体进度</small>
                <strong>
                  {completedPathCount} / {paths.length} 条已完成
                </strong>
              </span>
              <span>
                <small>{executionMode === "parallel" ? "当前并发" : "当前位置"}</small>
                <strong>
                  {executionMode === "parallel"
                    ? `${runningPathCount} 条运行中`
                    : runningPathIndex >= 0
                      ? `第 ${runningPathIndex + 1} / ${paths.length} 条`
                      : "正在建立运行记录"}
                </strong>
              </span>
            </div>
            <ol
              className="pathRunQueue"
              aria-label={`Path Agent ${executionMode === "parallel" ? "并行执行" : "串行执行"}状态`}
            >
              {pathRunStates.map(({ path, run, status }, index) => {
                const latestEvent = run?.events.at(-1);
                const statusLabel =
                  status === "RUNNING"
                    ? "正在推演"
                    : status === "SUCCEEDED"
                      ? "已完成"
                      : status === "FAILED"
                        ? "失败"
                        : executionMode === "parallel"
                          ? "启动中"
                          : "排队中";
                return (
                  <li className={status.toLowerCase()} key={path.id}>
                    <span className="pathRunIndex">
                      {status === "SUCCEEDED" ? "✓" : String(index + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <strong>{path.title}</strong>
                      <small>
                        {latestEvent
                          ? `${latestEvent.summary} · 已记录 ${run?.events.length ?? 0} 步`
                          : status === "QUEUED"
                            ? executionMode === "parallel"
                              ? "正在启动并行运行"
                              : "等待上一条 Path 完成"
                            : "正在启动 Path Agent"}
                      </small>
                    </div>
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
                  <i>{index < step ? "✓" : index + 1}</i>
                  {item}
                </span>
              ))}
            </div>
            <div className="aiProgress">
              <i style={{ width: `${Math.min(92, 18 + step * 24)}%` }} />
            </div>
          </>
        )}
        <p>你可以留在当前页面，结果完成后会自动出现；AI 只生成建议，不会替人批准业务承诺。</p>
        <section className="embeddedLiveTrace" aria-label="实时审计轨迹">
          <header>
            <span>
              <small>LIVE TRACE</small>
              <strong>实时审计轨迹</strong>
            </span>
            <em>每 600ms 刷新</em>
          </header>
          <AgentTracePanel runs={runs} agentType={agentType} paths={paths} autoExpand embedded />
        </section>
      </div>
    </section>
  );
}

export function CapabilityPanel({ details }: { details: CapabilityDetails }) {
  const groups = [
    {
      key: "policies" as const,
      label: "POLICY · 强制责任",
      note: "由平台结构化匹配并编译为 CommitmentDAG 责任节点",
    },
    {
      key: "skills" as const,
      label: "SKILL · 认知方法",
      note: "由 Agent Adapter 使用，不能代替业务审批",
    },
    {
      key: "knowledge" as const,
      label: "KNOWLEDGE · 建议材料",
      note: "带来源的历史观察，不是当前 Case 事实",
    },
  ];
  return (
    <section className="capabilityPanel" aria-label="Manifest 能力快照">
      <div className="capabilityHeader">
        <span>
          <strong>能力快照</strong>
          <small>{details.snapshot_status === "frozen" ? "已随 Manifest 冻结" : "当前预览"}</small>
        </span>
        <em>版本 + SHA-256</em>
      </div>
      <div className="capabilityGroups">
        {groups.map((group) => (
          <div className="capabilityGroup" key={group.key}>
            <div>
              <strong>{group.label}</strong>
              <small>{group.note}</small>
            </div>
            {details.assets[group.key].map((asset) => (
              <article key={asset.resolved_ref.id}>
                <span>
                  <b>{asset.title ?? asset.resolved_ref.id}</b>
                  <small>
                    {asset.resolved_ref.id} · v{asset.resolved_ref.version}
                  </small>
                </span>
                <span className={`assetSource ${asset.resolved_ref.source}`}>
                  {asset.resolved_ref.source}
                </span>
                <code>{asset.resolved_ref.digest.slice(7, 19)}</code>
                <p>
                  {asset.description ??
                    asset.content?.summary ??
                    asset.instructions?.[0] ??
                    `${asset.requirements?.commitments?.length ?? 0} 个强制责任节点`}
                </p>
              </article>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

export function ManifestYamlPanel({
  yaml,
  downloadHref,
  onCopy,
}: {
  yaml: string;
  downloadHref: string;
  onCopy: () => void;
}) {
  return (
    <section className="manifestYamlPanel" aria-label="完整 Manifest YAML">
      <header>
        <span>
          <strong>完整 Manifest YAML</strong>
          <small>全局 Knowledge 与所有 Path 的 Skill / Policy / Knowledge</small>
        </span>
        <span>
          <button className="linkButton" onClick={onCopy}>
            复制 YAML
          </button>
          <a className="linkButton" href={downloadHref} download>
            下载 YAML
          </a>
        </span>
      </header>
      <pre>{yaml}</pre>
    </section>
  );
}

function traceDuration(start: string, end: string | null) {
  if (!end) return null;
  const seconds = (Date.parse(end) - Date.parse(start)) / 1000;
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  return seconds < 60 ? `${seconds.toFixed(1)} 秒` : `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
}

function traceActivities(events: AgentTraceEvent[]) {
  const activities: { start: AgentTraceEvent; end?: AgentTraceEvent }[] = [];
  for (const event of events) {
    if (/^deepagent\.tool\.(completed|failed)$/.test(event.step)) {
      const candidates = activities.filter(({ start, end }) =>
        !end && start.step === "deepagent.tool.started" &&
        start.details.tool === event.details.tool &&
        (typeof event.details.call_id === "string"
          ? start.details.call_id === event.details.call_id
          : event.details.input !== undefined && JSON.stringify(start.details.input) === JSON.stringify(event.details.input)),
      );
      // Older traces have no call ID. Only combine an unambiguous match.
      if (candidates.length === 1) {
        candidates[0].end = event;
        continue;
      }
    }
    activities.push({ start: event });
  }
  return activities;
}

function TraceActivity({ start, end, running }: {
  start: AgentTraceEvent; end?: AgentTraceEvent; running: boolean;
}) {
  const event = end ?? start;
  const tool = typeof event.details.tool === "string" ? event.details.tool : null;
  const failed = event.status === "FAILED";
  const pending = !end && start.step === "deepagent.tool.started";
  const state = failed ? "failed" : pending && running ? "running" : pending ? "unknown" : "completed";
  const status = failed ? "失败" : pending ? (running ? "执行中" : "未记录结果") : event.status === "STARTED" ? "已发起" : "已完成";
  const duration = end ? traceDuration(start.created_at, end.created_at) : null;
  const input = start.details.input ?? event.details.input;
  const output = event.details.output;
  return (
    <li className={state}>
      <span className="traceSequence" aria-hidden="true">{failed ? "!" : tool ? "⌘" : "·"}</span>
      <details className={`traceActivity${tool ? " isTool" : ""}`} open={failed}>
        <summary>
          <span className="traceActivityTitle">
            {tool ? <><span className="traceKind">工具</span><code>{tool}</code></> : <strong>{event.summary}</strong>}
          </span>
          <span className="traceActivityMeta"><b>{status}</b>{duration && <time>{duration}</time>}<span className="traceChevron" aria-hidden="true">›</span></span>
        </summary>
        {tool && <p className="traceActivityDescription">{event.summary}</p>}
        <div className="traceActivityBody">
          {input !== undefined && <section><h4>输入参数</h4><pre>{typeof input === "string" ? input : JSON.stringify(input, null, 2)}</pre></section>}
          {output !== undefined && <section><h4>返回结果</h4><pre>{typeof output === "string" ? output : JSON.stringify(output, null, 2)}</pre></section>}
          {failed && <section className="traceFailure"><h4>错误详情</h4><pre>{JSON.stringify(event.details.error ?? event.details, null, 2)}</pre></section>}
          {typeof event.details.manifest_yaml === "string" && <section><h4>完整 Manifest YAML</h4><pre>{event.details.manifest_yaml}</pre></section>}
          <details className="tracePayload">
            <summary>原始审计记录 · {end ? "2 条" : `#${start.sequence}`}</summary>
            <pre>{JSON.stringify(end ? [start, end] : start, null, 2)}</pre>
          </details>
        </div>
      </details>
    </li>
  );
}

export function AgentTracePanel({
  runs,
  agentType,
  paths = [],
  autoExpand = false,
  embedded = false,
}: {
  runs: AgentRun[];
  agentType: "orchestrator" | "path" | "synthesis";
  paths?: ManifestPath[];
  autoExpand?: boolean;
  embedded?: boolean;
}) {
  const label =
    agentType === "orchestrator"
      ? "ORCHESTRATOR"
      : agentType === "path"
        ? "PATH AGENT"
        : "SYNTHESIS AGENT";
  const typedRuns = runs.filter((run) => run.agent_type === agentType);
  const statusLabel = { RUNNING: "运行中", SUCCEEDED: "已完成", FAILED: "失败" } as const;
  return (
    <section
      className={`agentTracePanel${embedded ? " embedded" : ""}`}
      aria-label={`${label} Trace`}
    >
      {!embedded && (
        <header className="traceHeader">
          <span>
            <strong>{label} TRACE</strong>
            <small>查看执行过程、工具调用与返回结果</small>
          </span>
          <em>{typedRuns.length} 次运行</em>
        </header>
      )}
      {typedRuns.length === 0 ? (
        <p className="emptyTrace">尚无 {label} 运行记录。</p>
      ) : (
        <div className="traceRuns">
          {typedRuns.map((run) => {
            const pathId = pathIdForRun(run);
            const pathTitle = agentType === "path"
              ? paths.find((path) => path.id === pathId)?.title ?? pathId ?? "未关联 Path"
              : null;
            return (
              <details
                className={`traceRun ${run.status.toLowerCase()}`}
                open={autoExpand && (run.status === "RUNNING" || run.status === "FAILED")}
                key={run.id}
              >
                <summary>
                  <span className="traceRunIdentity">
                    <i aria-hidden="true" />
                    <span>
                      <strong title={pathTitle ?? run.adapter_profile}>{pathTitle ?? run.adapter_profile}</strong>
                      {pathTitle && <small>{run.adapter_profile}</small>}
                      <small>
                        {formatThreadTime(run.started_at)} · {run.id.slice(0, 8)}
                      </small>
                    </span>
                  </span>
                  <span className="traceRunMeta">
                    <b>{statusLabel[run.status]}</b>
                    <small>{run.events.filter((event) => event.step === "deepagent.tool.started").length} 次工具调用 · {run.events.length} 条记录</small>
                  </span>
                </summary>
                <div className="traceRunBody">
                  <div className="traceRunOverview"><span>执行活动</span><span>{traceDuration(run.started_at, run.completed_at) ?? (run.status === "RUNNING" ? "实时更新" : "耗时未知")}</span></div>
                  {run.error_message && (
                    <p className="traceError">
                      {run.error_type}: {run.error_message}
                    </p>
                  )}
                  <ol className="traceSteps">
                    {traceActivities(run.events).map(({ start, end }) => (
                      <TraceActivity key={start.id} start={start} end={end} running={run.status === "RUNNING"} />
                    ))}
                  </ol>
                </div>
              </details>
            );
          })}
        </div>
      )}
    </section>
  );
}
