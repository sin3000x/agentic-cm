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

test("the global Sidebar renders on every route with its full destination set", async () => {
  // The Sidebar is shared layout: every route must expose the same navigation.
  for (const pathname of ["/", "/cases/CM-2026-014", "/assets/skills"]) {
    const html = await renderHtml(pathname);
    assert.match(html, /<nav [^>]*aria-label="主导航"/);
    for (const href of [
      '"/"',
      '"/cases/CM-2026-014"',
      '"/assets/skills"',
      '"/assets/policies"',
      '"/assets/knowledge"',
    ]) {
      assert.match(html, new RegExp(`href=${href}`), `${pathname} sidebar must link ${href}`);
    }
    // The inbox is a link from other routes but an in-place drawer trigger on
    // the workspace itself, so assert the affordance rather than the element.
    assert.match(html, /我的待办/, `${pathname} sidebar must expose the inbox`);
    // Identities are a demo simulation, never a real role switch.
    assert.doesNotMatch(html, /切换至该角色/);
  }
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

test("each asset route renders its own kind with a search affordance", async () => {
  for (const [path, heading] of [
    ["skills", "Skills"],
    ["policies", "Policies"],
    ["knowledge", "Knowledge"],
  ]) {
    const html = await renderHtml(`/assets/${path}`);
    assert.match(html, new RegExp(`<h1>${heading}</h1>`));
    assert.match(html, new RegExp(`aria-label="搜索 ${heading}"`));
    assert.match(html, /<section class="assetGrid" aria-live="polite"/);
  }
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
