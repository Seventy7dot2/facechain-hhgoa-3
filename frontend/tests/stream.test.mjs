import assert from "node:assert/strict";
import test from "node:test";
import { consumeEvents } from "../app/stream.mjs";

test("SSE parser preserves split frames and multi-byte image event text", async () => {
  const bytes = new TextEncoder().encode(': heartbeat\n\nid: 1\ndata: {"message":"pixels → proof"}\n\ndata: {"state":"finished"}\r\n\r\n');
  const stream = new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    controller.close();
  } });
  const events = [];
  await consumeEvents(stream, event => events.push(event));
  assert.deepEqual(events, [{ message: "pixels → proof" }, { state: "finished" }]);
});

test("SSE parser rejects truncated events", async () => {
  const stream = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode('data: {"state":'));
    controller.close();
  } });
  await assert.rejects(consumeEvents(stream, () => {}), /incomplete event/);
});
