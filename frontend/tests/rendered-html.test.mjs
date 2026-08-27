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

async function renderHtml(pathname = "/") {
  const response = await render(pathname);
  assert.equal(response.status, 200, `${pathname} must server-render successfully`);
  return response.text();
}

test("every route server-renders without throwing", async () => {
  for (const pathname of [
    "/",
    "/inbox",
    "/cases/CM-2026-014",
    "/assets/skills",
    "/assets/policies",
    "/assets/knowledge",
  ]) {
    const html = await renderHtml(pathname);
    assert.match(html, /<main/, `${pathname} must render a main landmark`);
    assert.doesNotMatch(html, /Application error|Internal Server Error/);
  }
});

test("the global Sidebar exposes overview, inbox, and organization assets without Case shortcuts", async () => {
  // The Sidebar is shared layout: every route must expose the same navigation.
  for (const pathname of ["/", "/inbox", "/cases/CM-2026-014", "/assets/skills"]) {
    const html = await renderHtml(pathname);
    assert.match(html, /<nav [^>]*aria-label="主导航"/);
    for (const href of [
      '"/"',
      '"/inbox"',
      '"/assets/skills"',
      '"/assets/policies"',
      '"/assets/knowledge"',
    ]) {
      assert.match(html, new RegExp(`href=${href}`), `${pathname} sidebar must link ${href}`);
    }
    assert.match(html, /我的待办/, `${pathname} sidebar must expose the inbox`);
    assert.doesNotMatch(html, />Case 工作台</, `${pathname} sidebar must not expose a Case-specific shortcut`);
    assert.doesNotMatch(html, />协作动态</, `${pathname} sidebar must not expose an activity shortcut`);
    // Identities are a demo simulation, never a real role switch.
    assert.doesNotMatch(html, /切换至该角色/);
  }
});

test("the inbox route renders a role-scoped cross-Case approval summary", async () => {
  const html = await renderHtml("/inbox");
  assert.match(html, /<h1>我的待办<\/h1>/);
  assert.match(html, /汇总所有 Case 中分配给当前角色/);
  assert.match(html, /正在同步待审批节点/);
});

test("the overview homepage renders its Case list, filters, and activity regions", async () => {
  const html = await renderHtml("/");
  assert.match(html, /<section class="metrics" aria-label="Case 指标"/);
  assert.match(html, /id="case-overview"/);
  // Status filters are a tablist with exactly one tab selected on first render.
  assert.match(html, /<div class="filterTabs" role="tablist"/);
  assert.equal((html.match(/role="tab"/g) ?? []).length, 4);
  assert.equal((html.match(/aria-selected="true"/g) ?? []).length, 1);
  assert.match(html, /id="activity"/);
});

test("the homepage keeps risk, ownership, and lifecycle columns visible", async () => {
  const html = await renderHtml("/");
  for (const heading of ["状态 / 风险", "当前阶段", "负责人", "承诺期限"]) {
    assert.match(html, new RegExp(heading));
  }
});

test("the homepage renders a loading state rather than fabricated Case data", async () => {
  // Case status and phase are authoritative from the Case API. Before that
  // request resolves the page must show a placeholder, never invented rows.
  const html = await renderHtml("/");
  assert.match(html, /正在同步 Case 状态/);
  assert.match(html, /状态与阶段以 Case API 为准/);
});

test("the Case workspace renders the governance thread for the requested Case", async () => {
  const html = await renderHtml("/cases/CM-2026-014");
  // The route parameter drives the rendered Case, not a hardcoded id.
  assert.match(html, /CM-2026-014/);
  assert.match(html, /<section class="caseThread" aria-label="Case 完整流转 Thread"/);
  assert.match(html, /Human Proposal/);
  assert.match(html, /<div class="futureFlow" aria-label="后续流程"/);
});

test("the Case workspace treats CLOSED as a completed workflow for every role", async () => {
  const source = await readFile(
    new URL("../app/cases/[id]/page.tsx", import.meta.url),
    "utf8",
  );
  // FINAL_REVIEW is retained as the last business phase after closure, so the
  // terminal Case status must override the right-rail phase presentation.
  assert.match(source, /const isCaseClosed = caseStatus === "CLOSED"/);
  assert.match(source, /isCaseClosed && index === activeStageIndex/);
  assert.match(source, /isCaseClosed \? "Case 已关闭"/);

  // Other roles cannot see the report body, but the redacted owner decision
  // still carries its revision and must not regress to "等待汇总".
  assert.match(source, /synthesisReport\?\.revision \?\? ownerDecision\?\.synthesis_revision/);
  assert.match(source, /Case Owner 已基于 Synthesis/);
});

test("resetting the Demo reaches the automatic orchestration refresh", async () => {
  const source = await readFile(
    new URL("../app/cases/[id]/page.tsx", import.meta.url),
    "utf8",
  );
  const resetDemo = source.slice(
    source.indexOf("async function resetDemo()"),
    source.indexOf("function togglePath("),
  );

  assert.doesNotMatch(resetDemo, /setShowInbox|setInboxItems/);
  assert.match(resetDemo, /automaticRunsRef\.current\.clear\(\)/);
  assert.match(resetDemo, /setCaseRefreshKey\(\(current\) => current \+ 1\)/);
});

test("Manifest statistics use compact Path-owned capability references", async () => {
  const source = await readFile(
    new URL("../app/cases/[id]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /policies:\s*ManifestAssetRef\[\]/);
  assert.match(source, /skills:\s*ManifestAssetRef\[\]/);
  assert.match(source, /knowledge:\s*ManifestAssetRef\[\]/);
  assert.match(source, /path\.policies\.length/g);
  assert.match(source, /path\.skills\.length/g);
  assert.match(source, /path\.knowledge\.length/g);
  assert.doesNotMatch(source, /capability_snapshots|compiled_policy|asset_payloads/);
  assert.doesNotMatch(source, /policy\.commitments/);
  assert.match(source, /查看完整 Manifest YAML/);
  assert.match(source, /manifest\.yaml/);
  assert.doesNotMatch(source, /查看替代 Path 能力快照/);
});

test("Orchestrator trace renders the complete Manifest YAML as YAML", async () => {
  const source = await readFile(
    new URL("../app/cases/[id]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /event\.details\.manifest_yaml/);
  assert.match(source, /完整 Manifest YAML/);
});

test("the Case Owner keeps a persistent approved Manifest material after review", async () => {
  const source = await readFile(
    new URL("../app/cases/[id]/page.tsx", import.meta.url),
    "utf8",
  );
  // The Manifest review UI is phase-specific, but the approved artifact must
  // remain reachable throughout every later Case phase.
  assert.match(source, /const hasApprovedManifest = canViewManifest/);
  for (const phase of ["PATH_EXPLORATION", "PROFESSIONAL_COMMITMENT", "FINAL_REVIEW"]) {
    assert.match(source, new RegExp(`hasApprovedManifest[\\s\\S]*${phase}`));
  }
  assert.match(source, /aria-label="已批准 Manifest"/);
  assert.match(source, /查看已批准 Manifest/);
  assert.match(source, /批准时冻结的 Manifest/);
  assert.match(source, /查看完整 Manifest YAML/);
  assert.match(source, /ManifestYamlPanel/);
});

test("each asset route renders its own kind with a search affordance", async () => {
  for (const [path, heading] of [
    ["skills", "Skills"],
    ["policies", "Policies"],
    ["knowledge", "Knowledge"],
  ]) {
    const html = await renderHtml(`/assets/${path}`);
    assert.match(html, new RegExp(`<h1>${heading}</h1>`));
    assert.match(html, new RegExp(`aria-label="搜索 ${heading}"`));
    assert.match(html, new RegExp(`<section class="${path === "skills" ? "skillHierarchy" : "assetGrid"}" aria-live="polite"`));
  }
});

test("the Skills library derives its hierarchy from paths and bundle members", async () => {
  const source = await readFile(new URL("../app/assets/asset-library.tsx", import.meta.url), "utf8");
  assert.match(source, /skill\.paths\?\.length/);
  assert.match(source, /skill\.members \?\? \[\]/);
  assert.match(source, /CASE PLAYBOOK/);
  assert.match(source, /PATH BUNDLE/);
  assert.match(source, /ATOMIC SKILL/);
  assert.doesNotMatch(source, /assigned_via|composition/);
});

test("stylesheets keep responsive breakpoints and honour reduced motion", async () => {
  // Asserted against CSS text because no visual-regression harness exists.
  // Whitespace-tolerant so reformatting the stylesheet does not fail this.
  const globals = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  const workspace = await readFile(
    new URL("../app/cases/[id]/case-detail.css", import.meta.url),
    "utf8",
  );
  for (const width of [1120, 760, 430]) {
    assert.match(globals, new RegExp(`@media\\s*\\(\\s*max-width\\s*:\\s*${width}px\\s*\\)`));
  }
  for (const styles of [globals, workspace]) {
    assert.match(styles, /prefers-reduced-motion/);
  }
});
