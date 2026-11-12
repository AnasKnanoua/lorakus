import { describe, expect, it } from "vitest";

import { readSse, type SseEvent } from "./sse";

function streamOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      }
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<SseEvent[]> {
  const events: SseEvent[] = [];
  for await (const event of readSse(stream)) {
    events.push(event);
  }
  return events;
}

const BODY =
  'event: delta\ndata: {"text": "Bonjour à toi "}\n\n' +
  'event: delta\ndata: {"text": "— ça va ?"}\n\n' +
  'event: done\ndata: {"status": "ok"}\n\n';

const EXPECTED: SseEvent[] = [
  { event: "delta", data: '{"text": "Bonjour à toi "}' },
  { event: "delta", data: '{"text": "— ça va ?"}' },
  { event: "done", data: '{"status": "ok"}' },
];

describe("readSse", () => {
  it("reads whole events", async () => {
    expect(await collect(streamOf([BODY]))).toEqual(EXPECTED);
  });

  it("survives a network split at every single byte position", async () => {
    const bytes = new TextEncoder().encode(BODY);
    for (let cut = 1; cut < bytes.length; cut++) {
      const events = await collect(streamOf([bytes.slice(0, cut), bytes.slice(cut)]));
      expect(events, `coupure a l'octet ${cut}`).toEqual(EXPECTED);
    }
  });

  it("accepts CRLF and lone CR line endings, even split between chunks", async () => {
    const crlf = BODY.replaceAll("\n", "\r\n");
    expect(await collect(streamOf([crlf]))).toEqual(EXPECTED);
    const half = crlf.indexOf("\r\n") + 1; // coupe entre \r et \n
    expect(await collect(streamOf([crlf.slice(0, half), crlf.slice(half)]))).toEqual(EXPECTED);
    expect(await collect(streamOf([BODY.replaceAll("\n", "\r")]))).toEqual(EXPECTED);
  });

  it("joins multi-line data, ignores comments and unknown fields", async () => {
    const body = ": battement\nevent: delta\ndata: a\ndata: b\nid: 7\n\n";
    expect(await collect(streamOf([body]))).toEqual([{ event: "delta", data: "a\nb" }]);
  });

  it("dispatches a last event that has no trailing blank line", async () => {
    expect(await collect(streamOf(["event: done\ndata: {}"]))).toEqual([
      { event: "done", data: "{}" },
    ]);
  });

  it("defaults the event name to message", async () => {
    expect(await collect(streamOf(["data: x\n\n"]))).toEqual([{ event: "message", data: "x" }]);
  });
});
