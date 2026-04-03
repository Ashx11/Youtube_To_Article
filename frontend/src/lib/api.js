const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.trim() || "http://localhost:8000";

async function postJson(path, payload) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "Request failed.";
    throw new Error(detail);
  }

  return data;
}

export function fetchTranscript(youtubeUrl) {
  return postJson("/api/transcripts/fetch", { youtube_url: youtubeUrl });
}

export async function streamArticleGeneration(options, handlers = {}) {
  const { youtubeUrl, provider, model, tone, temperature } = options;
  const response = await fetch(`${API_BASE_URL}/api/articles/generate/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({
      youtube_url: youtubeUrl,
      provider,
      model,
      tone,
      temperature,
    }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === "string" ? data.detail : "Request failed.";
    throw new Error(detail);
  }

  if (!response.body) {
    throw new Error("Streaming is not supported by this browser.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const part of parts) {
      const event = parseSseEvent(part);
      if (!event) {
        continue;
      }

      if (event.name === "transcript") {
        handlers.onTranscript?.(event.data);
        continue;
      }

      if (event.name === "chunk") {
        handlers.onChunk?.(event.data);
        continue;
      }

      if (event.name === "done") {
        handlers.onDone?.(event.data);
        continue;
      }

      if (event.name === "error") {
        throw new Error(event.data.detail || "Streaming request failed.");
      }
    }

    if (done) {
      break;
    }
  }
}

function parseSseEvent(rawEvent) {
  const lines = rawEvent.split("\n");
  let name = "message";
  const dataLines = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      name = line.slice(6).trim();
      continue;
    }

    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (!dataLines.length) {
    return null;
  }

  return {
    name,
    data: JSON.parse(dataLines.join("\n")),
  };
}
