import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

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
  assert.match(html, /Case 完整流转 Thread/);
  assert.match(html, /Human Proposal/);
  assert.match(html, /陈澄于.*时间读取中.*创建/);
  assert.doesNotMatch(html, /今天 08:46|今天 08:47|今天 09:02|今天 09:18/);
  assert.match(html, /平台完成 Case 受理/);
  assert.match(html, /专业承诺汇合/);
  assert.match(html, /Case Owner 最终决策/);
  assert.doesNotMatch(html, /受控行动与结果验证|结果验证/);
  assert.doesNotMatch(html, /王淼 · 主计划/);
  assert.doesNotMatch(html, /切换至该角色/);
  assert.match(html, /Demo identity simulation/);
  assert.match(html, /不连接或修改 ERP/);
  assert.doesNotMatch(html, /codex-preview|SkeletonPreview/);
});

test("client bundle uses the configured API base URL", async () => {
  const chunksDirectory = fileURLToPath(new URL("../dist/client/_next/static/chunks/", import.meta.url));
  const chunkNames = await readdir(chunksDirectory);
  const chunks = await Promise.all(
    chunkNames.filter((name) => name.endsWith(".js")).map((name) => readFile(`${chunksDirectory}/${name}`, "utf8")),
  );
  const pageChunk = chunks.find((contents) => contents.includes("/api/cases/CM-2026-014"));
  const localEnv = await readFile(new URL("../.env.local", import.meta.url), "utf8").catch(() => "");
  const localApiBase = localEnv.match(/^NEXT_PUBLIC_API_BASE_URL=(.+)$/m)?.[1]?.trim();
  const expectedApiBase = process.env.NEXT_PUBLIC_API_BASE_URL
    ?? localApiBase
    ?? `http://localhost:${process.env.AGENTIC_CM_API_PORT ?? "8000"}`;

  assert.ok(pageChunk, "could not find the Case page client bundle");
  assert.ok(pageChunk.includes(expectedApiBase), `client bundle does not use ${expectedApiBase}`);
  assert.match(pageChunk, /commitments\/.*\/approve/);
  assert.match(pageChunk, /批准并设为 READY/);
  assert.match(pageChunk, /等待本人批准/);
});

test("downstream DAG placement is independent from node status", async () => {
  const pageSource = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const styles = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

  assert.match(pageSource, /node\.depends_on\.length \? "downstream" : "upstream"/);
  assert.match(styles, /\.dagNode\.downstream\{grid-column:1\/-1;width:48%;justify-self:center\}/);
});

test("redacted Manifest views still render shared Commitment state", async () => {
  const pageSource = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");

  assert.match(pageSource, /\?\? commitmentNodes\[0\]\?\.path_id/);
  assert.match(pageSource, /node\.role === currentIdentity\.role \? "待本人批准" : `待\$\{node\.role\}批准`/);
});

test("Case Thread renders approval events with backend timestamps", async () => {
  const pageSource = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");

  assert.match(pageSource, /api\/cases\/CM-2026-014\/timeline/);
  assert.match(pageSource, /event\.event_type === "commitment\.approved"/);
  assert.match(pageSource, /formatThreadTime\(event\.created_at\)/);
});
