/**
 * SentinelMCPClient — Parry-aware wrapper over an MCP client session.
 *
 * Mirrors the Python SDK's `parry.mcp.client.SentinelMCPClient`.
 *
 * Lifecycle (stdio example):
 *
 * ```ts
 * await using mcp = await SentinelMCPClient.stdio({
 *   command: "npx",
 *   args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
 *   agentId: "agent_123",
 *   apiKey: "sk-parry-...",
 * });
 * const manifest = await mcp.listTools();
 * const result = await mcp.callTool("read_file", { path: "/tmp/a.txt" });
 * ```
 *
 * The underlying `@modelcontextprotocol/sdk` dependency is optional and
 * lazy-loaded — importing this module without it installed is fine, only
 * calling `connect()` (or `stdio({ mockManifest: ... })` in tests) requires it.
 */

import { MCPBlockedError, MCPManifestError, type MCPDetection } from "./errors.js";
import { manifestHash, type MCPManifest, type MCPTool } from "./normalize.js";

const DEFAULT_BASE_URL = "https://api.parry.dev";
const DEFAULT_TIMEOUT = 10_000;

export interface SentinelMCPClientOptions {
  agentId: string;
  apiKey?: string;
  parryBaseUrl?: string;
  blocking?: boolean;
  sandbox?: boolean;
  serverName?: string;
  /** Request timeout for the Parry backend round trip (ms). */
  timeout?: number;
}

export interface StdioTransportOptions extends SentinelMCPClientOptions {
  command: string;
  args?: string[];
  env?: Record<string, string>;
  /**
   * Test hook: skip spawning a real MCP subprocess and use this
   * manifest instead. The Parry backend round trip still runs so
   * the registration path stays exercised.
   */
  mockManifest?: MCPManifest;
}

interface MCPConnectionResponse {
  server_id: string;
  trust_level: string;
  reputation_score?: number;
  previous_trust_level?: string | null;
  detections?: MCPDetection[];
}

type TransportKind = "stdio";

interface StdioSession {
  listTools(): Promise<{ tools: Array<Record<string, unknown>> }>;
  callTool(params: { name: string; arguments: Record<string, unknown> }): Promise<unknown>;
  close?(): Promise<void>;
}

export class SentinelMCPClient {
  readonly agentId: string;
  readonly baseUrl: string;
  readonly blocking: boolean;
  readonly sandbox: boolean;
  readonly serverName: string | undefined;
  readonly timeout: number;

  private readonly apiKey: string | undefined;
  private readonly transport: TransportKind;
  private readonly stdioOptions: StdioTransportOptions | null;

  private manifest: MCPManifest | null = null;
  private serverUri: string | null = null;
  private session: StdioSession | null = null;
  private sessionCleanup: (() => Promise<void>) | null = null;
  private _serverId: string | null = null;
  private _trustLevel: string | null = null;

  private constructor(
    transport: TransportKind,
    stdioOptions: StdioTransportOptions | null,
    options: SentinelMCPClientOptions
  ) {
    this.transport = transport;
    this.stdioOptions = stdioOptions;
    this.agentId = options.agentId;
    this.apiKey = options.apiKey ?? process.env.PARRY_API_KEY;
    if (!this.apiKey && !options.sandbox) {
      throw new Error(
        "Parry API key required (pass apiKey or set PARRY_API_KEY)"
      );
    }
    this.baseUrl = (options.parryBaseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, "");
    this.blocking = options.blocking ?? true;
    this.sandbox = options.sandbox ?? false;
    this.serverName = options.serverName;
    this.timeout = options.timeout ?? DEFAULT_TIMEOUT;
  }

  /**
   * Factory for stdio-transport MCP servers. Opens the underlying
   * `@modelcontextprotocol/sdk` session, fetches the tool manifest,
   * and registers it with Parry.
   *
   * Tests can pass `mockManifest` to skip spawning a real subprocess.
   */
  static async stdio(options: StdioTransportOptions): Promise<SentinelMCPClient> {
    const client = new SentinelMCPClient("stdio", options, options);
    await client.connect();
    return client;
  }

  /** HTTP transport — not implemented in v1. */
  static async http(): Promise<SentinelMCPClient> {
    throw new Error("HTTP transport is not implemented in v1. Use stdio().");
  }

  /** SSE transport — not implemented in v1. */
  static async sse(): Promise<SentinelMCPClient> {
    throw new Error("SSE transport is not implemented in v1. Use stdio().");
  }

  // ── Connection lifecycle ─────────────────────────────────────────

  private async connect(): Promise<void> {
    if (this.transport !== "stdio" || this.stdioOptions === null) {
      throw new Error(`Unsupported transport: ${this.transport}`);
    }

    const args = this.stdioOptions.args ?? [];
    this.serverUri = `stdio://${this.stdioOptions.command} ${args.join(" ")}`.trim();

    if (this.sandbox) {
      this.manifest = { tools: [] };
      return;
    }

    if (this.stdioOptions.mockManifest !== undefined) {
      this.manifest = this.stdioOptions.mockManifest;
    } else {
      await this.openStdioSession();
    }

    await this.registerWithParry();
  }

  private async openStdioSession(): Promise<void> {
    if (this.stdioOptions === null) throw new Error("stdio options missing");

    let ClientCtor: new (info: { name: string; version: string }) => {
      connect(transport: unknown): Promise<void>;
      listTools(): Promise<{ tools: MCPTool[] }>;
      callTool(params: { name: string; arguments: Record<string, unknown> }): Promise<unknown>;
      close(): Promise<void>;
    };
    let StdioTransport: new (params: {
      command: string;
      args?: string[];
      env?: Record<string, string>;
    }) => unknown;

    try {
      // String indirection prevents TS/bundlers from resolving the
      // optional peer at build time. This is the same "lazy import"
      // pattern the Python SDK uses for its `mcp` extra.
      const clientSpec = "@modelcontextprotocol/sdk/client/index.js";
      const stdioSpec = "@modelcontextprotocol/sdk/client/stdio.js";
      const clientMod = (await import(clientSpec)) as {
        Client: typeof ClientCtor;
      };
      const stdioMod = (await import(stdioSpec)) as {
        StdioClientTransport: typeof StdioTransport;
      };
      ClientCtor = clientMod.Client;
      StdioTransport = stdioMod.StdioClientTransport;
    } catch {
      throw new Error(
        "SentinelMCPClient.stdio() requires the @modelcontextprotocol/sdk peer. " +
          "Install with: npm install @modelcontextprotocol/sdk"
      );
    }

    const transport = new StdioTransport({
      command: this.stdioOptions.command,
      args: this.stdioOptions.args,
      env: this.stdioOptions.env,
    });
    const client = new ClientCtor({ name: "parry-sentinel", version: "0.1.0" });
    await client.connect(transport);

    const tools = await client.listTools();
    this.manifest = {
      tools: (tools.tools ?? []).map((t) => ({
        name: t.name ?? "",
        description: t.description ?? "",
        inputSchema: t.inputSchema ?? {},
      })),
    };
    this.session = client as unknown as StdioSession;
    this.sessionCleanup = async () => {
      try {
        await client.close();
      } catch {
        // best effort
      }
    };
  }

  private async registerWithParry(): Promise<void> {
    if (this.manifest === null || this.serverUri === null) return;

    const payload = {
      agent_id: this.agentId,
      server_uri: this.serverUri,
      server_name: this.serverName,
      manifest: this.manifest,
    };

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}/api/v1/mcp/connections`, {
        method: "POST",
        headers: {
          "X-Parry-Secret": this.apiKey ?? "",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
    } catch {
      // Fail open — Parry unreachable must not block the developer.
      clearTimeout(timer);
      return;
    } finally {
      clearTimeout(timer);
    }

    if (res.status === 403) {
      const text = await safeText(res);
      await this.closeUnderlying();
      throw new MCPBlockedError(text || "MCP server blocked by org policy", {
        serverUri: this.serverUri,
      });
    }

    if (res.status >= 400) {
      // Log-and-continue parity with the Python SDK.
      return;
    }

    let data: MCPConnectionResponse;
    try {
      data = (await res.json()) as MCPConnectionResponse;
    } catch {
      return;
    }

    this._serverId = data.server_id ?? null;
    this._trustLevel = data.trust_level ?? null;

    const detections = data.detections ?? [];
    const critical = detections.filter((d) => d.severity === "critical");

    if (this.blocking && critical.length > 0) {
      await this.closeUnderlying();
      throw new MCPBlockedError(
        critical[0]?.reason ?? "Critical MCP detection",
        { detections, serverUri: this.serverUri }
      );
    }
  }

  private async closeUnderlying(): Promise<void> {
    if (this.sessionCleanup !== null) {
      await this.sessionCleanup();
      this.sessionCleanup = null;
      this.session = null;
    }
  }

  /** Close the underlying MCP session. Safe to call multiple times. */
  async close(): Promise<void> {
    await this.closeUnderlying();
  }

  // AsyncDisposable (TS 5.2+) — enables `await using mcp = ...`
  async [(Symbol as { asyncDispose?: symbol }).asyncDispose ??
    Symbol.for("Symbol.asyncDispose")](): Promise<void> {
    await this.close();
  }

  // ── Public methods ───────────────────────────────────────────────

  /** Return the cached manifest fetched at connect time. */
  async listTools(): Promise<MCPManifest> {
    if (this.manifest === null) {
      throw new MCPManifestError("SentinelMCPClient not connected");
    }
    return this.manifest;
  }

  /** Invoke a tool on the underlying MCP session. */
  async callTool(name: string, args: Record<string, unknown> = {}): Promise<unknown> {
    if (this.session === null) {
      throw new MCPManifestError(
        "SentinelMCPClient has no active MCP session (sandbox or mockManifest mode)"
      );
    }
    return this.session.callTool({ name, arguments: args });
  }

  /** SHA-256 of the canonical manifest. Empty string before connect(). */
  manifestHash(): string {
    if (this.manifest === null) return "";
    return manifestHash(this.manifest);
  }

  get serverId(): string | null {
    return this._serverId;
  }

  get trustLevel(): string | null {
    return this._trustLevel;
  }
}

async function safeText(res: Response): Promise<string> {
  try {
    return await res.text();
  } catch {
    return "";
  }
}
