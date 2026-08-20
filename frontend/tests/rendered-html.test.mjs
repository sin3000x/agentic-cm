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
  assert.match(html, /Case Owner Proposal/);
  assert.match(html, /陈澄 · 订单履行经理（Case Owner）/);
  assert.doesNotMatch(html, /王淼 · 主计划/);
  assert.doesNotMatch(html, /切换至该角色/);
  assert.match(html, /Demo identity simulation/);
  assert.match(html, /不连接或修改 ERP/);
  assert.doesNotMatch(html, /codex-preview|SkeletonPreview/);
});

test("client bundle uses the configured API port", async () => {
  const chunksDirectory = fileURLToPath(new URL("../dist/client/_next/static/chunks/", import.meta.url));
  const chunkNames = await readdir(chunksDirectory);
  const chunks = await Promise.all(
    chunkNames.filter((name) => name.endsWith(".js")).map((name) => readFile(`${chunksDirectory}/${name}`, "utf8")),
  );
  const pageChunk = chunks.find((contents) => contents.includes("/api/cases/CM-2026-014"));
  const expectedPort = process.env.AGENTIC_CM_API_PORT ?? "8000";

  assert.ok(pageChunk, "could not find the Case page client bundle");
  assert.match(pageChunk, new RegExp(`http://localhost:${expectedPort}\\b`));
});
