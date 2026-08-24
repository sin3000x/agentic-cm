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
  assert.match(html, /Northstar MCU-X7 订单预计延期 12 天/);
  assert.match(html, /Vela 一级供应商停机影响两个在途批次/);
  assert.match(html, /Northstar MCU-X7 替代料缺少客户认证/);
  assert.match(html, /Aster 9 月需求临时上调 22%/);
  assert.match(html, /售后备件消耗连续三周超出预测区间/);
  assert.match(html, /华南仓 WMS 与实收数量相差 320 件/);
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
