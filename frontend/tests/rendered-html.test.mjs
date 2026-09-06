import assert from "node:assert/strict";
import { access } from "node:fs/promises";
import test from "node:test";

const templateRoot = new URL("../", import.meta.url);

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the FaceChain product shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>FaceChain Live — See the search\. Prove the match\.<\/title>/i);
  assert.match(html, /SEE THE SEARCH/);
  assert.match(html, /RUN FACECHAIN/);
  assert.match(html, /REAL EVENT FEED/);
  assert.match(html, /HH GOA · TASK 03/);
});

test("removes the disposable starter preview", async () => {
  await assert.rejects(access(new URL("app/_sites-preview", templateRoot)));
  await assert.rejects(access(new URL("public/favicon.svg", templateRoot)));
});
