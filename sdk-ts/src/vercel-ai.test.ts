import { describe, it, expect, vi, beforeEach } from "vitest";
import { ParryClient } from "./client.js";
import { ParryBlockedError } from "./errors.js";
import { parryWrap, createParryWrapper } from "./vercel-ai.js";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
  });
}

describe("parryWrap", () => {
  let client: ParryClient;

  beforeEach(() => {
    mockFetch.mockReset();
    client = new ParryClient({
      apiKey: "sk-parry-test",
      baseUrl: "http://localhost:8000",
    });
  });

  it("passes through when check allows", async () => {
    // Mock proxy check → allowed
    mockFetch.mockReturnValueOnce(
      jsonResponse({ allowed: true, reason: "", detector: "", severity: null, confidence: 0 })
    );
    // Mock ingest → accepted
    mockFetch.mockReturnValueOnce(
      jsonResponse({ event_id: "123", status: "accepted" })
    );

    const mockResult = { text: "Hello!", usage: { promptTokens: 10, completionTokens: 5 } };
    const result = await parryWrap(client, async () => mockResult, {
      prompt: "Hi",
      model: "gpt-4o",
    });

    expect(result).toBe(mockResult);
    expect(mockFetch).toHaveBeenCalledTimes(2); // check + ingest
  });

  it("throws ParryBlockedError when blocked", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({
        allowed: false,
        reason: "Injection detected",
        detector: "prompt_injection",
        severity: "high",
        confidence: 0.95,
      })
    );

    await expect(
      parryWrap(client, async () => ({ text: "should not reach" }), {
        prompt: "evil prompt",
      })
    ).rejects.toThrow(ParryBlockedError);
  });

  it("extracts text from generateText result", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({ allowed: true, reason: "", detector: "", severity: null, confidence: 0 })
    );
    mockFetch.mockReturnValueOnce(jsonResponse({}));

    const result = await parryWrap(
      client,
      async () => ({
        text: "Generated response",
        usage: { promptTokens: 50, completionTokens: 100 },
        modelId: "gpt-4o",
      }),
      { prompt: "test" },
    );

    expect(result.text).toBe("Generated response");

    // Verify ingest was called with extracted data
    const ingestCall = mockFetch.mock.calls[1];
    const ingestBody = JSON.parse(ingestCall[1].body);
    expect(ingestBody.response).toBe("Generated response");
    expect(ingestBody.token_count).toBe(150);
  });

  it("extracts tool calls from result", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({ allowed: true, reason: "", detector: "", severity: null, confidence: 0 })
    );
    mockFetch.mockReturnValueOnce(jsonResponse({}));

    await parryWrap(
      client,
      async () => ({
        text: "",
        toolCalls: [
          { toolName: "search", args: { query: "test" } },
        ],
      }),
      { prompt: "test" },
    );

    const ingestBody = JSON.parse(mockFetch.mock.calls[1][1].body);
    expect(ingestBody.tool_calls).toHaveLength(1);
    expect(ingestBody.tool_calls[0].name).toBe("search");
  });

  it("handles null result gracefully", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({ allowed: true, reason: "", detector: "", severity: null, confidence: 0 })
    );
    mockFetch.mockReturnValueOnce(jsonResponse({}));

    const result = await parryWrap(client, async () => null);
    expect(result).toBeNull();
  });

  it("fails open when proxy check errors", async () => {
    mockFetch.mockRejectedValueOnce(new Error("Network error"));
    // Ingest call
    mockFetch.mockReturnValueOnce(jsonResponse({}));

    const result = await parryWrap(client, async () => ({ text: "ok" }));
    expect(result.text).toBe("ok");
  });

  it("measures latency", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({ allowed: true, reason: "", detector: "", severity: null, confidence: 0 })
    );
    mockFetch.mockReturnValueOnce(jsonResponse({}));

    await parryWrap(client, async () => {
      await new Promise((r) => setTimeout(r, 10));
      return { text: "done" };
    });

    const ingestBody = JSON.parse(mockFetch.mock.calls[1][1].body);
    expect(ingestBody.latency_ms).toBeGreaterThanOrEqual(10);
  });
});

describe("createParryWrapper", () => {
  let client: ParryClient;

  beforeEach(() => {
    mockFetch.mockReset();
    client = new ParryClient({
      apiKey: "sk-parry-test",
      baseUrl: "http://localhost:8000",
      agentId: "default-agent",
    });
  });

  it("creates a reusable wrapper with defaults", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({ allowed: true, reason: "", detector: "", severity: null, confidence: 0 })
    );
    mockFetch.mockReturnValueOnce(jsonResponse({}));

    const withParry = createParryWrapper(client, { agentId: "my-agent" });
    const result = await withParry(async () => ({ text: "hi" }));
    expect(result.text).toBe("hi");

    const checkBody = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(checkBody.agent_id).toBe("my-agent");
  });

  it("allows per-call option overrides", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({ allowed: true, reason: "", detector: "", severity: null, confidence: 0 })
    );
    mockFetch.mockReturnValueOnce(jsonResponse({}));

    const withParry = createParryWrapper(client, { agentId: "default" });
    await withParry(async () => ({ text: "hi" }), { agentId: "override" });

    const checkBody = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(checkBody.agent_id).toBe("override");
  });
});
