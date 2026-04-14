/**
 * Parry SDK client — handles event ingest and proxy checks.
 *
 * Fail-open contract: any error (network, timeout, non-200) results
 * in the call being allowed through. Parry must never be the reason
 * a valid LLM call gets dropped.
 */

import { ParryBlockedError, ParryPermissionDeniedError } from "./errors.js";

export interface ParryClientOptions {
  apiKey: string;
  baseUrl?: string;
  agentId?: string;
  /** Proxy check timeout in milliseconds (default: 2000) */
  timeout?: number;
}

export interface ProxyCheckRequest {
  agentId?: string;
  sessionId?: string;
  prompt?: string;
  model?: string;
  toolCalls?: Array<Record<string, unknown>>;
}

export interface ProxyCheckResult {
  allowed: boolean;
  reason: string;
  detector: string;
  severity: string | null;
  confidence: number;
}

export interface ScanResponseRequest {
  response: string;
  agentId?: string;
  sessionId?: string;
}

export interface ScanResponseResult {
  blocked: boolean;
  response: string | null;
  findings: Array<Record<string, unknown>>;
}

export interface EventIngestRequest {
  agentId?: string;
  sessionId?: string;
  prompt?: string;
  response?: string;
  model?: string;
  toolCalls?: Array<Record<string, unknown>>;
  latencyMs?: number;
  tokenCount?: number;
  metadata?: Record<string, unknown>;
}

const DEFAULT_TIMEOUT = 2000;
const SCAN_TIMEOUT = 2000;
const DEFAULT_BASE_URL = "https://api.parry.dev";

export class ParryClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  readonly defaultAgentId: string | null;
  private readonly timeout: number;

  constructor(options: ParryClientOptions) {
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, "");
    this.defaultAgentId = options.agentId ?? null;
    this.timeout = options.timeout ?? DEFAULT_TIMEOUT;
  }

  /**
   * Pre-flight check before an LLM call.
   *
   * Throws ParryBlockedError if the call is blocked.
   * Throws ParryPermissionDeniedError if a permission boundary denies it.
   * Any other error is swallowed (fail open).
   */
  async checkBeforeCall(req: ProxyCheckRequest): Promise<void> {
    const body = {
      agent_id: req.agentId ?? this.defaultAgentId,
      session_id: req.sessionId,
      prompt: req.prompt,
      model: req.model,
      tool_calls: req.toolCalls ?? [],
    };

    let data: ProxyCheckResult;
    try {
      data = await this.post<ProxyCheckResult>("/api/v1/proxy/check", body);
    } catch (e) {
      if (e instanceof ParryBlockedError) throw e;
      // Fail open on network/timeout/parse errors
      return;
    }

    if (!data.allowed) {
      if (data.detector === "permission_boundary") {
        throw new ParryPermissionDeniedError({
          reason: data.reason,
          toolName: extractToolName(data.reason),
        });
      }
      throw new ParryBlockedError({
        reason: data.reason,
        detector: data.detector,
        severity: data.severity ?? "high",
        confidence: data.confidence,
      });
    }
  }

  /**
   * Post-LLM response scan. Returns the (possibly redacted) response text.
   *
   * Throws ParryBlockedError only when the backend sets `blocked=true`
   * (mode=block + finding triggered). All other failures fail open and
   * return the original text unchanged — a scan error must never corrupt
   * the caller's output.
   */
  async scanResponse(req: ScanResponseRequest): Promise<string> {
    if (!req.response) return req.response;

    const body = {
      agent_id: req.agentId ?? this.defaultAgentId,
      session_id: req.sessionId,
      response: req.response,
    };

    let data: ScanResponseResult;
    try {
      data = await this.post<ScanResponseResult>(
        "/api/v1/proxy/scan-response",
        body,
        SCAN_TIMEOUT
      );
    } catch {
      return req.response;
    }

    if (data.blocked) {
      const findings = data.findings ?? [];
      const top = (findings[0]?.pattern as string | undefined) ?? "sensitive data";
      throw new ParryBlockedError({
        reason: `Sensitive data in response: ${top}`,
        detector: "data_exfiltration",
        severity: "high",
        confidence: 0.85,
      });
    }

    return data.response ?? req.response;
  }

  /**
   * Ingest an event (fire-and-forget). Never throws.
   */
  async ingestEvent(req: EventIngestRequest): Promise<void> {
    const body = {
      agent_id: req.agentId ?? this.defaultAgentId,
      session_id: req.sessionId,
      prompt: req.prompt,
      response: req.response,
      model: req.model,
      tool_calls: req.toolCalls ?? [],
      latency_ms: req.latencyMs,
      token_count: req.tokenCount,
      metadata: req.metadata,
    };

    try {
      await this.post("/api/v1/events/ingest", body);
    } catch {
      // Fire and forget — never block the caller
    }
  }

  private async post<T>(path: string, body: unknown, timeoutMs?: number): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs ?? this.timeout);

    try {
      const res = await fetch(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.apiKey}`,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!res.ok) {
        throw new Error(`Parry API returned ${res.status}`);
      }

      return (await res.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }
}

function extractToolName(reason: string): string | undefined {
  const match = reason.match(/'([^']+)'/);
  return match?.[1];
}
