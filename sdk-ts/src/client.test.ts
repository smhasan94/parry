import { describe, it, expect, vi, beforeEach } from "vitest";
import { ParryClient } from "./client.js";
import { ParryBlockedError, ParryPermissionDeniedError } from "./errors.js";

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

describe("ParryClient", () => {
  let client: ParryClient;

  beforeEach(() => {
    mockFetch.mockReset();
    client = new ParryClient({
      apiKey: "sk-parry-test",
      baseUrl: "http://localhost:8000",
      agentId: "test-agent",
    });
  });

  describe("checkBeforeCall", () => {
    it("does nothing when allowed", async () => {
      mockFetch.mockReturnValueOnce(
        jsonResponse({ allowed: true, reason: "", detector: "", severity: null, confidence: 0 })
      );
      await expect(client.checkBeforeCall({ prompt: "hello" })).resolves.toBeUndefined();
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
      await expect(client.checkBeforeCall({ prompt: "evil" })).rejects.toThrow(
        ParryBlockedError
      );
    });

    it("throws ParryPermissionDeniedError for permission_boundary", async () => {
      mockFetch.mockReturnValueOnce(
        jsonResponse({
          allowed: false,
          reason: "Tool 'delete_db' is explicitly blocked",
          detector: "permission_boundary",
          severity: "high",
          confidence: 1.0,
        })
      );
      await expect(client.checkBeforeCall({ prompt: "test" })).rejects.toThrow(
        ParryPermissionDeniedError
      );
    });

    it("fails open on network error", async () => {
      mockFetch.mockRejectedValueOnce(new Error("Network error"));
      await expect(client.checkBeforeCall({ prompt: "hello" })).resolves.toBeUndefined();
    });

    it("fails open on non-200 status", async () => {
      mockFetch.mockReturnValueOnce(jsonResponse({}, 500));
      await expect(client.checkBeforeCall({ prompt: "hello" })).resolves.toBeUndefined();
    });

    it("sends correct headers", async () => {
      mockFetch.mockReturnValueOnce(
        jsonResponse({ allowed: true, reason: "", detector: "", severity: null, confidence: 0 })
      );
      await client.checkBeforeCall({ prompt: "test" });
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/proxy/check",
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            Authorization: "Bearer sk-parry-test",
            "Content-Type": "application/json",
          }),
        })
      );
    });

    it("uses default agent ID", async () => {
      mockFetch.mockReturnValueOnce(
        jsonResponse({ allowed: true, reason: "", detector: "", severity: null, confidence: 0 })
      );
      await client.checkBeforeCall({ prompt: "test" });
      const body = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(body.agent_id).toBe("test-agent");
    });
  });

  describe("scanResponse", () => {
    it("returns original text when not blocked and not redacted", async () => {
      mockFetch.mockReturnValueOnce(
        jsonResponse({ blocked: false, response: "hello world", findings: [] })
      );
      const out = await client.scanResponse({ response: "hello world" });
      expect(out).toBe("hello world");
    });

    it("returns redacted text when backend redacts in place", async () => {
      mockFetch.mockReturnValueOnce(
        jsonResponse({ blocked: false, response: "hello [REDACTED]", findings: [] })
      );
      const out = await client.scanResponse({ response: "hello 123-45-6789" });
      expect(out).toBe("hello [REDACTED]");
    });

    it("throws ParryBlockedError when blocked", async () => {
      mockFetch.mockReturnValueOnce(
        jsonResponse({
          blocked: true,
          response: null,
          findings: [{ pattern: "ssn" }],
        })
      );
      await expect(
        client.scanResponse({ response: "leak: 123-45-6789" })
      ).rejects.toThrow(ParryBlockedError);
    });

    it("fails open on network error", async () => {
      mockFetch.mockRejectedValueOnce(new Error("Network error"));
      const out = await client.scanResponse({ response: "hello" });
      expect(out).toBe("hello");
    });

    it("fails open on non-200 status", async () => {
      mockFetch.mockReturnValueOnce(jsonResponse({}, 500));
      const out = await client.scanResponse({ response: "hello" });
      expect(out).toBe("hello");
    });

    it("short-circuits on empty response", async () => {
      const out = await client.scanResponse({ response: "" });
      expect(out).toBe("");
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("posts to scan-response endpoint", async () => {
      mockFetch.mockReturnValueOnce(
        jsonResponse({ blocked: false, response: "hi", findings: [] })
      );
      await client.scanResponse({ response: "hi" });
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/proxy/scan-response",
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  describe("ingestEvent", () => {
    it("sends event without throwing", async () => {
      mockFetch.mockReturnValueOnce(jsonResponse({ event_id: "123", status: "accepted" }));
      await expect(
        client.ingestEvent({ prompt: "hi", response: "hello" })
      ).resolves.toBeUndefined();
    });

    it("swallows errors silently", async () => {
      mockFetch.mockRejectedValueOnce(new Error("fail"));
      await expect(
        client.ingestEvent({ prompt: "hi" })
      ).resolves.toBeUndefined();
    });

    it("posts to ingest endpoint", async () => {
      mockFetch.mockReturnValueOnce(jsonResponse({}));
      await client.ingestEvent({ prompt: "hi", model: "gpt-4o" });
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/events/ingest",
        expect.objectContaining({ method: "POST" })
      );
    });
  });
});

describe("ParryClient options", () => {
  it("strips trailing slash from baseUrl", () => {
    const client = new ParryClient({
      apiKey: "test",
      baseUrl: "http://localhost:8000/",
    });
    expect(client.defaultAgentId).toBeNull();
  });

  it("defaults agentId to null", () => {
    const client = new ParryClient({ apiKey: "test" });
    expect(client.defaultAgentId).toBeNull();
  });
});
