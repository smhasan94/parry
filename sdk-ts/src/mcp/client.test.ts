import { describe, it, expect, vi, beforeEach } from "vitest";
import { SentinelMCPClient } from "./client.js";
import { MCPBlockedError } from "./errors.js";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  } as unknown as Response);
}

function textResponse(body: string, status: number) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(body),
    json: () => Promise.reject(new Error("not json")),
  } as unknown as Response);
}

const MANIFEST = {
  tools: [
    { name: "read_file", description: "Read a file", inputSchema: {} },
    { name: "list_dir", description: "List a directory", inputSchema: {} },
  ],
};

describe("SentinelMCPClient.stdio()", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("registers the manifest with Parry on connect", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({
        server_id: "srv_1",
        trust_level: "observed",
        reputation_score: 50,
        detections: [],
      })
    );

    const mcp = await SentinelMCPClient.stdio({
      command: "fake-server",
      args: ["--foo"],
      agentId: "agent_1",
      apiKey: "sk-parry-test",
      parryBaseUrl: "http://localhost:8000",
      mockManifest: MANIFEST,
    });

    expect(mcp.serverId).toBe("srv_1");
    expect(mcp.trustLevel).toBe("observed");

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/mcp/connections");
    const body = JSON.parse(init.body as string);
    expect(body.agent_id).toBe("agent_1");
    expect(body.server_uri).toBe("stdio://fake-server --foo");
    expect(body.manifest.tools).toHaveLength(2);
    expect((init.headers as Record<string, string>)["X-Parry-Secret"]).toBe(
      "sk-parry-test"
    );
  });

  it("raises MCPBlockedError on 403", async () => {
    mockFetch.mockReturnValueOnce(textResponse("trust level=blocked", 403));

    await expect(
      SentinelMCPClient.stdio({
        command: "fake",
        agentId: "agent_1",
        apiKey: "k",
        parryBaseUrl: "http://localhost:8000",
        mockManifest: MANIFEST,
      })
    ).rejects.toThrow(MCPBlockedError);
  });

  it("raises MCPBlockedError on any critical detection", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({
        server_id: "srv_2",
        trust_level: "suspicious",
        detections: [
          {
            detector: "mcp_manifest",
            severity: "critical",
            reason: "Unicode smuggling in tool description",
          },
        ],
      })
    );

    await expect(
      SentinelMCPClient.stdio({
        command: "fake",
        agentId: "agent_1",
        apiKey: "k",
        parryBaseUrl: "http://localhost:8000",
        mockManifest: MANIFEST,
      })
    ).rejects.toMatchObject({
      name: "MCPBlockedError",
      reason: "Unicode smuggling in tool description",
    });
  });

  it("does not raise on critical detection when blocking=false", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({
        server_id: "srv_3",
        trust_level: "suspicious",
        detections: [{ severity: "critical", reason: "bad" }],
      })
    );

    const mcp = await SentinelMCPClient.stdio({
      command: "fake",
      agentId: "agent_1",
      apiKey: "k",
      parryBaseUrl: "http://localhost:8000",
      mockManifest: MANIFEST,
      blocking: false,
    });
    expect(mcp.trustLevel).toBe("suspicious");
  });

  it("fails open if Parry backend unreachable", async () => {
    mockFetch.mockRejectedValueOnce(new Error("ENOTFOUND"));

    const mcp = await SentinelMCPClient.stdio({
      command: "fake",
      agentId: "agent_1",
      apiKey: "k",
      parryBaseUrl: "http://localhost:8000",
      mockManifest: MANIFEST,
    });
    // Connected, no crash; no server_id available because the request failed.
    expect(mcp.serverId).toBeNull();
    const tools = await mcp.listTools();
    expect(tools.tools).toHaveLength(2);
  });

  it("logs and continues on non-403 4xx", async () => {
    mockFetch.mockReturnValueOnce(textResponse("rate limited", 429));

    const mcp = await SentinelMCPClient.stdio({
      command: "fake",
      agentId: "agent_1",
      apiKey: "k",
      parryBaseUrl: "http://localhost:8000",
      mockManifest: MANIFEST,
    });
    expect(mcp.serverId).toBeNull();
  });

  it("sandbox mode skips Parry registration", async () => {
    const mcp = await SentinelMCPClient.stdio({
      command: "fake",
      agentId: "agent_1",
      parryBaseUrl: "http://localhost:8000",
      sandbox: true,
      mockManifest: MANIFEST,
    });
    expect(mockFetch).not.toHaveBeenCalled();
    const tools = await mcp.listTools();
    expect(tools.tools).toEqual([]);
  });

  it("requires apiKey unless in sandbox mode", async () => {
    delete process.env.PARRY_API_KEY;
    await expect(
      SentinelMCPClient.stdio({
        command: "fake",
        agentId: "agent_1",
        mockManifest: MANIFEST,
      })
    ).rejects.toThrow(/api key/i);
  });

  it("manifestHash is stable and non-empty after connect", async () => {
    mockFetch.mockReturnValueOnce(
      jsonResponse({
        server_id: "srv_4",
        trust_level: "observed",
        detections: [],
      })
    );

    const mcp = await SentinelMCPClient.stdio({
      command: "fake",
      agentId: "agent_1",
      apiKey: "k",
      parryBaseUrl: "http://localhost:8000",
      mockManifest: MANIFEST,
    });

    expect(mcp.manifestHash()).toMatch(/^[a-f0-9]{64}$/);
  });

  it("callTool throws when there's no live session (sandbox)", async () => {
    const mcp = await SentinelMCPClient.stdio({
      command: "fake",
      agentId: "agent_1",
      parryBaseUrl: "http://localhost:8000",
      sandbox: true,
      mockManifest: MANIFEST,
    });
    await expect(mcp.callTool("x")).rejects.toThrow(/no active MCP session/);
  });
});

describe("SentinelMCPClient transports", () => {
  it("http() throws NotImplemented", async () => {
    await expect(SentinelMCPClient.http()).rejects.toThrow(/not implemented/i);
  });

  it("sse() throws NotImplemented", async () => {
    await expect(SentinelMCPClient.sse()).rejects.toThrow(/not implemented/i);
  });
});
