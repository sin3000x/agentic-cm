import assert from "node:assert/strict";
import test from "node:test";

const workerUrl = new URL("../dist/server/index.js", import.meta.url);
workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
const workerPromise = import(workerUrl.href).then(({ default: worker }) => worker);

async function render(pathname = "/") {
  const worker = await workerPromise;
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

test("the global Sidebar exposes overview, inbox, and organization assets", async () => {
  const html = await renderHtml("/");
  assert.match(html, /<nav [^>]*aria-label="主导航"/);
  for (const href of ['"/"', '"/inbox"', '"/assets/skills"', '"/assets/policies"', '"/assets/knowledge"']) {
    assert.match(html, new RegExp(`href=${href}`));
  }
  assert.match(html, /我的待办/);
});

test("the inbox route renders a role-scoped approval summary", async () => {
  const html = await renderHtml("/inbox");
  assert.match(html, /<h1>我的待办<\/h1>/);
});

test("the overview homepage renders Case regions", async () => {
  const html = await renderHtml("/");
  assert.match(html, /<section class="metrics" aria-label="Case 指标"/);
  assert.match(html, /id="case-overview"/);
});

test("the Case workspace renders the requested Case id", async () => {
  const html = await renderHtml("/cases/CM-2026-014");
  assert.match(html, /CM-2026-014/);
});

test("each asset route renders its own kind", async () => {
  for (const [path, heading] of [
    ["skills", "Skills"],
    ["policies", "Policies"],
    ["knowledge", "Knowledge"],
  ]) {
    const html = await renderHtml(`/assets/${path}`);
    assert.match(html, new RegExp(`<h1>${heading}</h1>`));
  }
});
