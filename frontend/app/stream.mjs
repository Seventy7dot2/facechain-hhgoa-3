/** Consume SSE over a multipart POST, preserving frames across arbitrary network chunks. */
export async function consumeEvents(stream, onEvent) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const data = frame.split(/\r?\n/).filter(line => line.startsWith("data:"))
          .map(line => line.slice(5).trimStart()).join("\n");
        if (data) onEvent(JSON.parse(data));
      }
      if (done) {
        if (buffer.trim()) throw new Error("The server sent an incomplete event.");
        break;
      }
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
