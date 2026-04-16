import { describe, it, expect, vi, beforeEach } from "vitest";
import { ParryClient } from "./client.js";
import { ParryBlockedError } from "./errors.js";
import { parryOpenAI } from "./openai.js";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
  });
}

function allowedCheck() {
  return jsonResponse({
    allowed: true,
    reason: "",
    detector: "",
    severity: null,
    confidence: 0,
  });
}

function cleanScan(text: string) {
  return jsonResponse({ blocked: false, response: text, findings: [] });
}

function makeOpenAIMock(content: string | null = "Hello", model = "gpt-4o") {
  const create = vi.fn().mockResolvedValue({
    id: "chatcmpl-1",
    model,
    choices: [{ message: { role: "assistant", content } }],
    usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
  });
  return { client: { chat: { completions: { create } } }, create };
}

describe("parryOpenAI", () => {
  let parry: ParryClient;

  beforeEach(() => {
    mockFetch.mockReset();
    parry = new ParryClient({
      apiKey: "sk-parry-test",
      baseUrl: "http://localhost:8000",
      agentId: "test-agent",
    });
  });

  it("passes through when allowed and scan clean", async () => {
    mockFetch
      .mockReturnValueOnce(allowedCheck())
      .mockReturnValueOnce(cleanScan("Hello"))
      .mockReturnValueOnce(jsonResponse({}));

    const { client, create } = makeOpenAIMock("Hello");
    const wrapped = parryOpenAI(client, parry);

    const result = await wrapped.chat.completions.create({
      model: "gpt-4o",
      messages: [{ role: "user", content: "hi" }],
    });

    expect(create).toHaveBeenCalledOnce();
    expect(result.choices[0].message.content).toBe("Hello");
  });

  it("throws ParryBlockedError on pre-call block", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({
        allowed: false,
        reason: "Prompt injection",
        detector: "prompt_injection",
        severity: "high",
        confidence: 0.95,
      })
    );

    const { client, create } = makeOpenAIMock();
    const wrapped = parryOpenAI(client, parry);

    await expect(
      wrapped.chat.completions.create({
        model: "gpt-4o",
        messages: [{ role: "user", content: "bad prompt" }],
      })
    ).rejects.toThrow(ParryBlockedError);

    expect(create).not.toHaveBeenCalled();
  });

  it("redacts response when backend returns different text", async () => {
    mockFetch
      .mockReturnValueOnce(allowedCheck())
      .mockReturnValueOnce(cleanScan("SSN: [REDACTED]"))
      .mockReturnValueOnce(jsonResponse({}));

    const { client } = makeOpenAIMock("SSN: 123-45-6789");
    const wrapped = parryOpenAI(client, parry);

    const result = await wrapped.chat.completions.create({
      model: "gpt-4o",
      messages: [{ role: "user", content: "show ssn" }],
    });

    expect(result.choices[0].message.content).toBe("SSN: [REDACTED]");
  });

  it("sends tool definitions in pre-call check", async () => {
    mockFetch
      .mockReturnValueOnce(allowedCheck())
      .mockReturnValueOnce(cleanScan("ok"))
      .mockReturnValueOnce(jsonResponse({}));

    const { client } = makeOpenAIMock("ok");
    const wrapped = parryOpenAI(client, parry);

    await wrapped.chat.completions.create({
      model: "gpt-4o",
      messages: [{ role: "user", content: "use the tool" }],
      tools: [{ type: "function", function: { name: "get_weather" } }],
    });

    const checkCall = mockFetch.mock.calls[0];
    const body = JSON.parse(checkCall[1].body);
    expect(body.tool_calls).toEqual([{ name: "get_weather" }]);
  });

  it("passes through non-chat properties", async () => {
    const { client } = makeOpenAIMock();
    (client as unknown as { models: string }).models = "list";
    const wrapped = parryOpenAI(client, parry);
    expect((wrapped as unknown as { models: string }).models).toBe("list");
  });

  describe("streaming", () => {
    function makeStreamingMock(
      chunks: Array<{
        id?: string;
        model?: string;
        choices: Array<{ delta: { content?: string | null; role?: string } }>;
      }>
    ) {
      async function* generate() {
        for (const c of chunks) yield c;
      }

      const stream = { [Symbol.asyncIterator]: () => generate() };
      const create = vi.fn().mockReturnValue(stream);
      return { client: { chat: { completions: { create } } }, create };
    }

    it("yields all chunks and ingests assembled text after stream completes", async () => {
      mockFetch
        .mockReturnValueOnce(allowedCheck())
        .mockReturnValueOnce(jsonResponse({}));

      const chunks = [
        { id: "c1", model: "gpt-4o", choices: [{ delta: { role: "assistant" } }] },
        { id: "c1", model: "gpt-4o", choices: [{ delta: { content: "Hello" } }] },
        { id: "c1", model: "gpt-4o", choices: [{ delta: { content: " there" } }] },
      ];

      const { client } = makeStreamingMock(chunks);
      const wrapped = parryOpenAI(client, parry);
      const result = await wrapped.chat.completions.create({
        model: "gpt-4o",
        messages: [{ role: "user", content: "hi" }],
        stream: true,
      });

      const collected: unknown[] = [];
      for await (const chunk of result as AsyncIterable<unknown>) {
        collected.push(chunk);
      }
      expect(collected).toHaveLength(3);

      const ingestCall = mockFetch.mock.calls.find((c) =>
        (c[0] as string).endsWith("/events/ingest")
      );
      expect(ingestCall).toBeDefined();
      const body = JSON.parse((ingestCall as [string, { body: string }])[1].body);
      expect(body.response).toBe("Hello there");
      expect(body.model).toBe("gpt-4o");
    });

    it("runs pre-call check before streaming begins", async () => {
      mockFetch.mockReturnValueOnce(
        jsonResponse({
          allowed: false,
          reason: "Blocked",
          detector: "prompt_injection",
          severity: "high",
          confidence: 0.9,
        })
      );

      const { client, create } = makeStreamingMock([]);
      const wrapped = parryOpenAI(client, parry);

      await expect(
        wrapped.chat.completions.create({
          model: "gpt-4o",
          messages: [{ role: "user", content: "bad" }],
          stream: true,
        })
      ).rejects.toThrow(ParryBlockedError);

      expect(create).not.toHaveBeenCalled();
    });

    it("ingests event even when no content deltas exist", async () => {
      mockFetch
        .mockReturnValueOnce(allowedCheck())
        .mockReturnValueOnce(jsonResponse({}));

      const { client } = makeStreamingMock([
        { id: "c1", model: "gpt-4o", choices: [{ delta: { role: "assistant" } }] },
      ]);
      const wrapped = parryOpenAI(client, parry);

      const result = await wrapped.chat.completions.create({
        model: "gpt-4o",
        messages: [{ role: "user", content: "hi" }],
        stream: true,
      });

      for await (const _ of result as AsyncIterable<unknown>) {
        // consume
      }

      const ingestCall = mockFetch.mock.calls.find((c) =>
        (c[0] as string).endsWith("/events/ingest")
      );
      expect(ingestCall).toBeDefined();
      const body = JSON.parse((ingestCall as [string, { body: string }])[1].body);
      expect(body.response).toBeUndefined();
    });

    it("does not run response scan on streaming responses", async () => {
      mockFetch
        .mockReturnValueOnce(allowedCheck())
        .mockReturnValueOnce(jsonResponse({}));

      const { client } = makeStreamingMock([
        { id: "c1", model: "gpt-4o", choices: [{ delta: { content: "secret" } }] },
      ]);
      const wrapped = parryOpenAI(client, parry);

      const result = await wrapped.chat.completions.create({
        model: "gpt-4o",
        messages: [{ role: "user", content: "hi" }],
        stream: true,
      });

      for await (const _ of result as AsyncIterable<unknown>) {
        // consume
      }

      const scanCall = mockFetch.mock.calls.find((c) =>
        (c[0] as string).endsWith("/scan-response")
      );
      expect(scanCall).toBeUndefined();
    });
  });
});
