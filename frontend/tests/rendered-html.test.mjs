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
  assert.match(html, /订单预计延期/);
  assert.match(html, /供应商交付异常/);
  assert.match(html, /替代料认证缺口/);
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
  assert.match(html, /Path 探索/);
  assert.match(html, /最终决策/);
  assert.match(html, /结果验证/);
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
  assert.match(html, /订单预计延期/);
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
  assert.doesNotMatch(workspaceSource, /className="caseList"|className="navItem"|className="identity"/);
  assert.doesNotMatch(workspaceStyles, /^\.sidebar\{|^\.brand\{|^\.nav\{|^\.identity\{/m);
});

test("homepage has desktop, tablet, mobile, and reduced-motion styles", async () => {
  const styles = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  assert.match(styles, /@media\(max-width:1120px\)/);
  assert.match(styles, /@media\(max-width:760px\)/);
  assert.match(styles, /@media\(max-width:430px\)/);
  assert.match(styles, /prefers-reduced-motion/);
});
