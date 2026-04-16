import { describe, it, expect, vi, beforeEach } from "vitest";
import { ParryClient } from "./client.js";
import { ParryCallbackHandler } from "./langchain.js";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
  });
}

describe("ParryCallbackHandler", () => {
  let parry: ParryClient;
  let handler: ParryCallbackHandler;

  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockReturnValue(jsonResponse({}));
    parry = new ParryClient({
      apiKey: "sk-parry-test",
      baseUrl: "http://localhost:8000",
      agentId: "test-agent",
    });
    handler = new ParryCallbackHandler(parry, {
      agentId: "lc-agent",
      sessionId: "sess-1",
    });
  });

  it("ingests event on handleLLMEnd after handleChatModelStart", () => {
    handler.handleChatModelStart(
      { kwargs: { model_name: "gpt-4o" } },
      [[{ content: "Hello world" }]],
      "run-1",
    );

    handler.handleLLMEnd(
      {
        generations: [[{ text: "Hi there" }]],
        llm_output: { token_usage: { total_tokens: 42 } },
      },
      "run-1",
    );

    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toContain("/events/ingest");
    const body = JSON.parse(opts.body);
    expect(body.agent_id).toBe("lc-agent");
    expect(body.session_id).toBe("sess-1");
    expect(body.prompt).toBe("Hello world");
    expect(body.response).toBe("Hi there");
    expect(body.model).toBe("gpt-4o");
    expect(body.token_count).toBe(42);
    expect(body.latency_ms).toBeGreaterThanOrEqual(0);
  });

  it("ingests event on handleLLMEnd after handleLLMStart (plain LLM)", () => {
    handler.handleLLMStart(
      { kwargs: { model: "text-davinci-003" } },
      ["What is 2+2?"],
      "run-2",
    );

    handler.handleLLMEnd(
      { generations: [[{ text: "4" }]], llm_output: null },
      "run-2",
    );

    expect(mockFetch).toHaveBeenCalledOnce();
    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.prompt).toBe("What is 2+2?");
    expect(body.response).toBe("4");
    expect(body.model).toBe("text-davinci-003");
  });

  it("extracts model from serialized.id fallback", () => {
    handler.handleChatModelStart(
      { id: ["langchain", "chat_models", "ChatAnthropic"] },
      [[{ content: "hi" }]],
      "run-3",
    );

    handler.handleLLMEnd(
      { generations: [[{ text: "hey" }]], llm_output: null },
      "run-3",
    );

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.model).toBe("ChatAnthropic");
  });

  it("extracts multipart content from messages", () => {
    handler.handleChatModelStart(
      { kwargs: { model_name: "gpt-4o" } },
      [[{
        content: [
          { type: "text", text: "Look at this" },
          { type: "image_url", image_url: "..." },
          { type: "text", text: "and tell me" },
        ],
      }]],
      "run-4",
    );

    handler.handleLLMEnd(
      { generations: [[{ text: "I see" }]], llm_output: null },
      "run-4",
    );

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.prompt).toBe("Look at this and tell me");
  });

  it("extracts tool_calls from generation message", () => {
    handler.handleChatModelStart(
      { kwargs: { model_name: "gpt-4o" } },
      [[{ content: "weather?" }]],
      "run-5",
    );

    handler.handleLLMEnd(
      {
        generations: [[{
          text: "",
          message: {
            tool_calls: [
              { name: "get_weather", args: { city: "SF" } },
            ],
          },
        }]],
        llm_output: null,
      },
      "run-5",
    );

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.tool_calls).toEqual([
      { name: "get_weather", arguments: { city: "SF" } },
    ]);
  });

  it("tracks tool calls via handleToolStart with parent run", () => {
    handler.handleChatModelStart(
      { kwargs: { model_name: "gpt-4o" } },
      [[{ content: "do stuff" }]],
      "run-6",
    );

    handler.handleToolStart(
      { name: "calculator" },
      "2+2",
      "tool-run-1",
      "run-6",
    );
    handler.handleToolEnd("4", "tool-run-1", "run-6");

    handler.handleLLMEnd(
      { generations: [[{ text: "done" }]], llm_output: null },
      "run-6",
    );

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.tool_calls).toEqual([{ name: "calculator" }]);
  });

  it("ignores tool calls without matching parent run", () => {
    handler.handleToolStart(
      { name: "orphan_tool" },
      "input",
      "tool-run-2",
      "nonexistent-parent",
    );

    // Should not throw
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("cleans up run state on handleLLMError", () => {
    handler.handleChatModelStart(
      { kwargs: { model_name: "gpt-4o" } },
      [[{ content: "fail" }]],
      "run-7",
    );

    handler.handleLLMError(new Error("boom"), "run-7");

    // Subsequent handleLLMEnd for same runId should be a no-op
    handler.handleLLMEnd(
      { generations: [[{ text: "ghost" }]], llm_output: null },
      "run-7",
    );

    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("uses defaultAgentId from ParryClient when no agentId in options", () => {
    const handlerNoOpts = new ParryCallbackHandler(parry);

    handlerNoOpts.handleLLMStart(
      { kwargs: { model: "gpt-4o" } },
      ["hi"],
      "run-8",
    );
    handlerNoOpts.handleLLMEnd(
      { generations: [[{ text: "hey" }]], llm_output: null },
      "run-8",
    );

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.agent_id).toBe("test-agent");
  });

  it("handles empty messages array gracefully", () => {
    handler.handleChatModelStart(
      { kwargs: { model_name: "gpt-4o" } },
      [[]],
      "run-9",
    );

    handler.handleLLMEnd(
      { generations: [[{ text: "ok" }]], llm_output: null },
      "run-9",
    );

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.prompt).toBeUndefined();
  });

  it("has name property for LangChain identification", () => {
    expect(handler.name).toBe("ParryCallbackHandler");
  });
});
