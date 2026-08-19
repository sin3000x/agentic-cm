import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Case workspace", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Agentic Case Management/);
  assert.match(html, /订单预计延期/);
  assert.match(html, /Case Owner Proposal/);
  assert.match(html, /陈澄 · 订单履行经理（Case Owner）/);
  assert.doesNotMatch(html, /王淼 · 主计划/);
  assert.doesNotMatch(html, /切换至该角色/);
  assert.match(html, /Demo identity simulation/);
  assert.match(html, /不连接或修改 ERP/);
  assert.doesNotMatch(html, /codex-preview|SkeletonPreview/);
});
