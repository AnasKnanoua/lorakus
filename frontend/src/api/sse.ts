/**
 * Lecture d'un flux Server-Sent Events (text/event-stream) envoye en reponse a un POST.
 *
 * EventSource ne sait faire que des GET : on lit donc le corps de la reponse nous-memes.
 * Les morceaux recus du reseau peuvent couper un evenement n'importe ou (au milieu d'une
 * ligne, d'un caractere multi-octets ou entre \r et \n) : le texte est reassemble avant
 * d'etre decoupe en evenements.
 */

export interface SseEvent {
  event: string;
  data: string;
}

export async function* readSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = stream.getReader();
  // Mode flux : un caractere multi-octets coupe entre deux morceaux est reassemble.
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "message";
  let data: string[] = [];

  const flushLine = function* (line: string): Generator<SseEvent> {
    if (line === "") {
      if (data.length > 0) {
        yield { event, data: data.join("\n") };
      }
      event = "message";
      data = [];
      return;
    }
    if (line.startsWith(":")) {
      return; // commentaire (battement de coeur)
    }
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }
    if (field === "event") {
      event = value;
    } else if (field === "data") {
      data.push(value);
    }
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      // Un \r final peut etre suivi d'un \n dans le prochain morceau : on l'attend.
      let match: RegExpExecArray | null;
      const lineEnd = /\r\n|\n|\r(?!$)/g;
      let consumed = 0;
      while ((match = lineEnd.exec(buffer)) !== null) {
        yield* flushLine(buffer.slice(consumed, match.index));
        consumed = match.index + match[0].length;
      }
      buffer = buffer.slice(consumed);
    }
    if (buffer.length > 0) {
      yield* flushLine(buffer.replace(/\r$/, ""));
    }
    yield* flushLine("");
  } finally {
    reader.releaseLock();
  }
}
