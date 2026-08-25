import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render(pathname = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request(`http://localhost${pathname}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Case overview homepage", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Case 总览/);
  assert.match(html, /早上好，陈澄/);
  assert.match(html, /进行中 Case/);
  assert.match(html, /需要你的关注/);
  assert.match(html, /正在同步 Case 状态/);
  assert.match(html, /状态与阶段以 Case API 为准/);
  assert.match(html, /Human governed/);
  assert.doesNotMatch(html, /切换至该角色/);
  assert.doesNotMatch(html, /codex-preview|SkeletonPreview/);
});

test("homepage keeps risk, ownership, and lifecycle visible", async () => {
  const response = await render();
  const html = await response.text();
  assert.match(html, /状态 \/ 风险/);
  assert.match(html, /当前阶段/);
  assert.match(html, /负责人/);
  assert.match(html, /承诺期限/);
  assert.match(html, /正在同步 Case 状态/);
});

test("homepage derives authoritative status and phase from the Case API", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(source, /fetch\(`\$\{API_BASE\}\/api\/cases`/);
  assert.match(source, /OPEN:"处理中",PENDING:"暂缓",CLOSED:"已关闭"/);
  assert.match(source, /PROFESSIONAL_COMMITMENT:\{value:4,label:"专业承诺"\}/);
  assert.match(source, /cases\.map\(mapCase\)/);
  assert.doesNotMatch(source, /const caseData: CaseSummary\[\] = \[/);
  assert.match(source, /Case 状态同步失败，当前列表可能不是最新/);
});

test("homepage implements search, filters, and quick view without role shortcuts", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const sidebarSource = await readFile(new URL("../app/app-sidebar.tsx", import.meta.url), "utf8");
  assert.match(source, /setActiveFilter/);
  assert.match(source, /setSearch/);
  assert.match(source, /setSelectedCase/);
  assert.match(source, /\/cases\/\$\{item\.id\}/);
  assert.match(source, /role="dialog"/);
  assert.match(source, /<AppSidebar/);
  assert.match(sidebarSource, /identityButton/);
  assert.match(sidebarSource, /Demo identity simulation/);
  assert.match(sidebarSource, /不连接或修改 ERP/);
  assert.doesNotMatch(source, /切换至该角色/);
});

test("order delay Case opens the original Case workspace", async () => {
  const response = await render("/cases/CM-2026-014");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /CM-2026-014/);
  assert.match(html, /Northstar MCU-X7 订单预计延期 12 天/);
  assert.match(html, /Case 完整流转 Thread/);
  assert.match(html, /Human Proposal/);
  assert.match(html, /从 Case 组装 Manifest|审查 Path Manifest|物料替代 · 审批 DAG/);
  assert.match(html, /Case 总览/);
  assert.match(html, /Case 工作台/);
  assert.match(html, /系统运行正常/);
  assert.doesNotMatch(html, /切换至该角色/);
});

test("overview and Case workspace use the same global Sidebar", async () => {
  const homeSource = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const workspaceSource = await readFile(new URL("../app/cases/[id]/page.tsx", import.meta.url), "utf8");
  const sidebarSource = await readFile(new URL("../app/app-sidebar.tsx", import.meta.url), "utf8");
  const workspaceStyles = await readFile(new URL("../app/cases/[id]/case-detail.css", import.meta.url), "utf8");

  assert.match(homeSource, /<AppSidebar active="overview"/);
  assert.match(workspaceSource, /<AppSidebar/);
  assert.match(workspaceSource, /active=\{showInbox \? "inbox" : "workspace"\}/);
  assert.match(sidebarSource, /Case 总览/);
  assert.match(sidebarSource, /Case 工作台/);
  assert.match(sidebarSource, /identityButton/);
  assert.match(sidebarSource, /\/assets\/skills/);
  assert.match(sidebarSource, /\/assets\/policies/);
  assert.match(sidebarSource, /\/assets\/knowledge/);
  assert.doesNotMatch(workspaceSource, /className="caseList"|className="navItem"|className="identity"/);
  assert.doesNotMatch(workspaceStyles, /^\.sidebar\{|^\.brand\{|^\.nav\{|^\.identity\{/m);
});

test("DAG and cross-Case Inbox share role-scoped approval decisions", async () => {
  const source = await readFile(new URL("../app/cases/[id]/page.tsx", import.meta.url), "utf8");
  const styles = await readFile(new URL("../app/cases/[id]/case-detail.css", import.meta.url), "utf8");

  assert.match(source, /api\/inbox/);
  assert.match(source, /commitments\/\$\{node\.id\}\/decision/);
  assert.match(source, /node\.status !== "PENDING" \|\| node\.role !== currentIdentity\.role/);
  assert.match(source, />通过<\/button>/);
  assert.match(source, />修改<\/button>/);
  assert.match(source, />否决<\/button>/);
  assert.match(source, /approvalActions\("CM-2026-014", node\)/);
  assert.match(source, /approvalActions\(item\.case_id, item\.node\)/);
  assert.match(source, /汇总所有 Case/);
  assert.match(styles, /\.approvalActions/);
});

test("approved Manifest launches a real Path Agent and exposes its audited SolutionRevision", async () => {
  const source = await readFile(new URL("../app/cases/[id]/page.tsx", import.meta.url), "utf8");
  const styles = await readFile(new URL("../app/cases/[id]/case-detail.css", import.meta.url), "utf8");

  assert.match(source, /paths\/\$\{pathId\}\/execute/);
  assert.match(source, /startAutomaticManifest\(\)/);
  assert.match(source, /startAutomaticAlternatives\(pendingPathIds\)/);
  assert.match(source, /await generateAlternatives\(approvedPathIds\)/);
  assert.match(source, /Orchestrator Agent 正在为您组装探索清单/);
  assert.match(source, /Path Agent 正在为您推演解决方案/);
  assert.match(source, /phase === "PATH_EXPLORATION"/);
  assert.match(source, /phase === "PROFESSIONAL_COMMITMENT"/);
  assert.match(source, /专业承诺 · 审批 DAG/);
  assert.match(source, /全部完成后，本阶段自动结束，平台才会开放专业承诺审批/);
  assert.match(source, /PROFESSIONAL_COMMITMENT: 3/);
  assert.match(source, /explorationCompleted \? "Path 探索完成，进入专业承诺"/);
  assert.match(source, /<AiWorkingCard kind=\{aiRunKind\} step=\{aiRunStep\}/);
  assert.doesNotMatch(source, /onClick=\{generateManifest\}>生成 Manifest/);
  assert.doesNotMatch(source, />生成替代方案<\/button>/);
  assert.match(source, /solutionRevision\.options\.map/);
  assert.match(source, /solutionRevision\.role_reports\.map/);
  assert.match(source, /三个角色的替代判断报告/);
  assert.match(source, /isSolutionRevision\(activePathAttempt\?\.solution_revision\)/);
  assert.match(source, /Agent 建议（非业务决定）/);
  assert.match(source, /agent_type: "path"/);
  assert.match(source, /event\.step === "run\.started" && event\.details\.path_id === solutionRevision\.path_id/);
  assert.match(source, /run\.agent_type === "path" && run\.events\.some/);
  assert.match(source, /phase === "MANIFEST_REVIEW" && agentRuns\.some\(\(run\) => run\.agent_type === "orchestrator"\)/);
  assert.match(source, /const typedRuns = runs\.filter\(\(run\) => run\.agent_type === agentType\)/);
  assert.match(source, /<AgentTracePanel runs=\{activePathAgentRuns\} agentType="path"/);
  assert.match(source, /查看当前 Path Trace/);
  assert.match(source, /查看 Orchestrator Trace/);
  assert.doesNotMatch(source, /查看 Agent Trace/);
  assert.doesNotMatch(source, /setShowAgentTrace\(true\)/);
  assert.doesNotMatch(source, /open=\{runIndex === 0\}/);
  assert.match(source, /solution_revision\.proposed/);
  assert.match(styles, /\.solutionRevision/);
  assert.match(styles, /\.solutionOptions/);
  assert.match(styles, /\.roleReports/);
  assert.match(styles, /\.aiWorkingCard/);
  assert.match(styles, /\.pathExplorationProgress/);
  assert.match(styles, /@keyframes aiScan/);
  assert.match(styles, /prefers-reduced-motion/);
});

test("organization asset pages read all three effective asset kinds from the backend", async () => {
  const source = await readFile(new URL("../app/assets/asset-library.tsx", import.meta.url), "utf8");
  assert.match(source, /\/api\/capabilities/);
  assert.match(source, /group === "skills"/);
  assert.match(source, /group === "policies"/);
  assert.match(source, /content\?\.observations/);
  for (const path of ["skills", "policies", "knowledge"]) {
    const response = await render(`/assets/${path}`);
    assert.equal(response.status, 200);
    assert.match(await response.text(), new RegExp(path[0].toUpperCase() + path.slice(1)));
  }
});

test("homepage has desktop, tablet, mobile, and reduced-motion styles", async () => {
  const styles = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  assert.match(styles, /@media\(max-width:1120px\)/);
  assert.match(styles, /@media\(max-width:760px\)/);
  assert.match(styles, /@media\(max-width:430px\)/);
  assert.match(styles, /prefers-reduced-motion/);
});
