import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
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

test("makes linked profiles and confirmed posts the dedicated final output", async () => {
  const source = await readFile(new URL("app/page.tsx", templateRoot), "utf8");
  assert.match(source, /FINAL DISCOVERY OUTPUT/);
  assert.match(source, /LINKED SOCIAL/);
  assert.match(source, /SOCIAL PROFILES/);
  assert.match(source, /PROFILES &amp; POSTS/);
  assert.match(source, /scrollIntoView/);
});

test("keeps the real event feed bounded and following the latest event", async () => {
  const page = await readFile(new URL("app/page.tsx", templateRoot), "utf8");
  const styles = await readFile(new URL("app/globals.css", templateRoot), "utf8");
  assert.match(page, /facechain:\/\/pipeline\/events/);
  assert.match(page, /JUMP TO LATEST/);
  assert.match(page, /eventLogRef\.current/);
  assert.match(styles, /\.event-log\s*\{[^}]*height:\s*450px[^}]*overflow-y:\s*auto/s);
});
