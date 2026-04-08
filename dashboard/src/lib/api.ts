import type {
  Agent,
  AgentEvent,
  ApiKey,
  ApiKeyCreated,
  AuditEntry,
  Incident,
  IncidentStatus,
  Policy,
  Severity,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_URL || "";

class ApiClient {
  private tokenGetter: (() => Promise<string | null>) | null = null;

  setTokenGetter(getter: () => Promise<string | null>) {
    this.tokenGetter = getter;
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...((options.headers as Record<string, string>) || {}),
    };

    if (this.tokenGetter) {
      const token = await this.tokenGetter();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    }

    const res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers,
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const err = new ApiError(res.status, body.detail || "Request failed", body.code);
      // 402 = plan quota or feature gate tripped. Broadcast a global
      // event so the UpgradeModal mounted at the layout level can
      // prompt the user without every caller needing to handle it.
      if (res.status === 402 && typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("parry:upgrade-required", { detail: { message: err.message } }),
        );
      }
      throw err;
    }

    if (res.status === 204) return undefined as T;
    return res.json();
  }

  // Agents
  async listAgents(): Promise<Agent[]> {
    return this.request("/api/v1/agents");
  }

  async getAgent(agentId: string): Promise<Agent> {
    return this.request(`/api/v1/agents/${agentId}`);
  }

  async createAgent(data: { name: string; description?: string }): Promise<Agent> {
    return this.request("/api/v1/agents", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async updateAgent(agentId: string, data: Partial<Agent>): Promise<Agent> {
    return this.request(`/api/v1/agents/${agentId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async deleteAgent(agentId: string): Promise<void> {
    return this.request(`/api/v1/agents/${agentId}`, { method: "DELETE" });
  }

  async recomputeBaseline(agentId: string): Promise<Agent> {
    return this.request(`/api/v1/agents/${agentId}/baseline/recompute`, {
      method: "POST",
    });
  }

  async recomputeAllBaselines(): Promise<{
    recomputed: number;
    skipped: number;
    errored: number;
  }> {
    return this.request(`/api/v1/agents/baselines/recompute-all`, {
      method: "POST",
    });
  }

  // Events
  async listEvents(
    agentId: string,
    cursor?: string
  ): Promise<{ events: AgentEvent[]; next_cursor: string | null; has_more: boolean }> {
    const params = new URLSearchParams({ agent_id: agentId });
    if (cursor) params.set("cursor", cursor);
    return this.request(`/api/v1/events?${params}`);
  }

  async getEvent(eventId: string): Promise<AgentEvent> {
    return this.request(`/api/v1/events/${eventId}`);
  }

  // Incidents
  async listIncidents(filters?: {
    severity?: Severity;
    status?: IncidentStatus;
    cursor?: string;
  }): Promise<{ incidents: Incident[]; next_cursor: string | null; has_more: boolean }> {
    const params = new URLSearchParams();
    if (filters?.severity) params.set("severity", filters.severity);
    if (filters?.status) params.set("status", filters.status);
    if (filters?.cursor) params.set("cursor", filters.cursor);
    return this.request(`/api/v1/incidents?${params}`);
  }

  async getIncident(incidentId: string): Promise<Incident> {
    return this.request(`/api/v1/incidents/${incidentId}`);
  }

  async updateIncident(
    incidentId: string,
    data: { status?: IncidentStatus; title?: string }
  ): Promise<Incident> {
    return this.request(`/api/v1/incidents/${incidentId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  // Policies
  async listPolicies(): Promise<Policy[]> {
    return this.request("/api/v1/policies");
  }

  async getPolicy(policyId: string): Promise<Policy> {
    return this.request(`/api/v1/policies/${policyId}`);
  }

  async createPolicy(data: Partial<Policy>): Promise<Policy> {
    return this.request("/api/v1/policies", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async updatePolicy(policyId: string, data: Partial<Policy>): Promise<Policy> {
    return this.request(`/api/v1/policies/${policyId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async deletePolicy(policyId: string): Promise<void> {
    return this.request(`/api/v1/policies/${policyId}`, { method: "DELETE" });
  }

  // API Keys
  async listApiKeys(): Promise<ApiKey[]> {
    return this.request("/api/v1/api-keys");
  }

  async createApiKey(name: string): Promise<ApiKeyCreated> {
    return this.request("/api/v1/api-keys", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  }

  async revokeApiKey(keyId: string): Promise<ApiKey> {
    return this.request(`/api/v1/api-keys/${keyId}`, { method: "DELETE" });
  }

  // Billing
  async createBillingPortal(returnUrl: string): Promise<{ url: string }> {
    const params = new URLSearchParams({ return_url: returnUrl });
    return this.request(`/api/v1/billing/portal?${params}`, { method: "POST" });
  }

  async getPlan(): Promise<PlanResponse> {
    return this.request("/api/v1/billing/plan");
  }

  async createCheckoutSession(
    priceId: string,
    successUrl: string,
    cancelUrl: string,
  ): Promise<{ url: string }> {
    const params = new URLSearchParams({
      price_id: priceId,
      success_url: successUrl,
      cancel_url: cancelUrl,
    });
    return this.request(`/api/v1/billing/checkout?${params}`, { method: "POST" });
  }

  // Alerts
  async getAlertConfig(): Promise<AlertConfig> {
    return this.request("/api/v1/alerts");
  }

  async updateAlertConfig(data: {
    slack_webhook_url?: string;
    alert_emails?: string[];
    webhook_url?: string;
    webhook_headers?: Record<string, string>;
    pagerduty_routing_key?: string;
    opsgenie_api_key?: string;
    min_severity?: string;
  }): Promise<AlertConfig> {
    return this.request("/api/v1/alerts", {
      method: "PUT",
      body: JSON.stringify(data),
    });
  }

  async deleteAlertConfig(): Promise<void> {
    return this.request("/api/v1/alerts", { method: "DELETE" });
  }

  async sendTestAlert(
    channel: "slack" | "email" | "webhook" | "pagerduty" | "opsgenie" = "slack"
  ): Promise<{ status: string }> {
    return this.request(`/api/v1/alerts/test?channel=${channel}`, { method: "POST" });
  }

  // Detector config
  async getDetectorConfig(): Promise<DetectorConfig> {
    return this.request("/api/v1/detector-config");
  }

  async getDefaultDetectorConfig(): Promise<DetectorConfig> {
    return this.request("/api/v1/detector-config/defaults");
  }

  async updateDetectorConfig(
    config: Record<
      string,
      { trigger_threshold?: number; enabled?: boolean; sigma_threshold?: number }
    >
  ): Promise<DetectorConfig> {
    return this.request("/api/v1/detector-config", {
      method: "PUT",
      body: JSON.stringify(config),
    });
  }

  async resetDetectorConfig(): Promise<void> {
    return this.request("/api/v1/detector-config", { method: "DELETE" });
  }

  // Metrics query
  async getAnomalyDriftHistogram(): Promise<AnomalyDriftHistogram> {
    return this.request("/api/v1/metrics/anomaly-drift");
  }

  // Blocking mode settings
  async getBlockingSettings(): Promise<{ blocking_enabled: boolean }> {
    return this.request("/api/v1/proxy/settings");
  }

  async updateBlockingSettings(
    body: { blocking_enabled: boolean }
  ): Promise<{ blocking_enabled: boolean }> {
    return this.request("/api/v1/proxy/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  }

  async getResponseScanSettings(): Promise<{ response_scan_mode: string }> {
    return this.request("/api/v1/proxy/scan-settings");
  }

  async updateResponseScanSettings(
    body: { response_scan_mode: "off" | "redact" | "block" }
  ): Promise<{ response_scan_mode: string }> {
    return this.request("/api/v1/proxy/scan-settings", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  }

  // Custom rules
  async listCustomRules(): Promise<CustomRule[]> {
    return this.request("/api/v1/custom-rules");
  }

  async createCustomRule(body: CustomRuleInput): Promise<CustomRule> {
    return this.request("/api/v1/custom-rules", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  async updateCustomRule(
    ruleId: string,
    body: Partial<CustomRuleInput>,
  ): Promise<CustomRule> {
    return this.request(`/api/v1/custom-rules/${ruleId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  }

  async deleteCustomRule(ruleId: string): Promise<void> {
    return this.request(`/api/v1/custom-rules/${ruleId}`, { method: "DELETE" });
  }

  async testCustomRule(body: {
    pattern: string;
    sample: string;
  }): Promise<{ matched: boolean; error: string | null; match: string | null }> {
    return this.request("/api/v1/custom-rules/test", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  // Agent behavioural stats (charts on AgentDetailPage)
  async getAgentStats(agentId: string, window: "7d" | "30d" | "90d"): Promise<AgentStats> {
    return this.request(`/api/v1/agents/${agentId}/stats?window=${window}`);
  }

  // Session replay
  async listAgentSessions(agentId: string, limit = 20): Promise<SessionSummary[]> {
    return this.request(`/api/v1/agents/${agentId}/sessions?limit=${limit}`);
  }

  async getSession(sessionId: string): Promise<SessionReplay> {
    return this.request(`/api/v1/sessions/${sessionId}`);
  }

  // Compliance reports — returns a PDF blob (binary) rather than JSON.
  async downloadComplianceReport(start: string, end: string): Promise<Blob> {
    const headers: Record<string, string> = {};
    if (this.tokenGetter) {
      const token = await this.tokenGetter();
      if (token) headers["Authorization"] = `Bearer ${token}`;
    }
    const params = new URLSearchParams({ start, end });
    const res = await fetch(
      `${BASE_URL}/api/v1/reports/compliance?${params}`,
      { headers },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body.detail || "Report generation failed", body.code);
    }
    return res.blob();
  }

  // Audit log
  async listAuditLog(filters?: {
    action?: string;
    resource_type?: string;
    resource_id?: string;
    cursor?: string;
  }): Promise<{ entries: AuditEntry[]; next_cursor: string | null; has_more: boolean }> {
    const params = new URLSearchParams();
    if (filters?.action) params.set("action", filters.action);
    if (filters?.resource_type) params.set("resource_type", filters.resource_type);
    if (filters?.resource_id) params.set("resource_id", filters.resource_id);
    if (filters?.cursor) params.set("cursor", filters.cursor);
    return this.request(`/api/v1/audit-log?${params}`);
  }
}

export interface AlertConfig {
  slack_webhook_url: string | null;
  alert_emails: string[];
  webhook_url: string | null;
  webhook_headers: Record<string, string>;
  // Backend returns a masked preview ("****abcd") when configured, null otherwise.
  pagerduty_routing_key: string | null;
  opsgenie_api_key: string | null;
  min_severity: string;
  enabled: boolean;
}

export interface DetectorEntry {
  trigger_threshold: number;
  enabled: boolean;
  is_default: boolean;
  sigma_threshold?: number;
}

export interface DetectorConfig {
  detectors: Record<string, DetectorEntry>;
}

export interface DriftBucket {
  le: number | null; // null represents the +Inf tail bucket
  count: number;
}

export interface DriftSeries {
  quality: string;
  triggered: boolean;
  total: number;
  sum: number;
  buckets: DriftBucket[];
}

export interface AnomalyDriftHistogram {
  series: DriftSeries[];
  note: string;
}

export type CustomRuleTarget = "prompt" | "response" | "both";
export type CustomRuleSeverity = "low" | "medium" | "high" | "critical";

export interface CustomRule {
  id: string;
  name: string;
  pattern: string;
  target: CustomRuleTarget;
  severity: CustomRuleSeverity;
  enabled: boolean;
  created_at: string;
}

export interface CustomRuleInput {
  name: string;
  pattern: string;
  target: CustomRuleTarget;
  severity: CustomRuleSeverity;
  enabled: boolean;
}

export interface AgentStats {
  window: "7d" | "30d" | "90d";
  generated_at: string;
  event_volume: { date: string; count: number }[];
  tool_calls: { tool: string; count: number }[];
  model_usage: { model: string; count: number }[];
  anomaly_trend: { date: string; avg_score: number }[];
  detection_counts: Record<string, number>;
}

export interface SessionSummary {
  id: string;
  agent_id: string;
  started_at: string | null;
  ended_at: string | null;
  event_count: number;
  is_live: boolean;
}

export interface SessionDetection {
  id: string;
  detector: string;
  severity: "critical" | "high" | "medium" | "low";
  confidence: number;
  reason: string;
  triggered: boolean;
}

export interface SessionReplayEvent {
  id: string;
  timestamp: string | null;
  model: string | null;
  latency_ms: number | null;
  token_count: number | null;
  tool_calls: Record<string, unknown>[];
  prompt_preview: string | null;
  response_preview: string | null;
  // Admin-only, omitted for viewers
  prompt?: string | null;
  response?: string | null;
  detections: SessionDetection[];
}

export interface SessionReplay {
  session: {
    id: string;
    agent_id: string;
    agent_name: string;
    started_at: string | null;
    ended_at: string | null;
    event_count: number;
    triggered_detection_count: number;
    metadata: Record<string, unknown>;
  };
  events: SessionReplayEvent[];
}

export interface PlanResponse {
  plan: "free" | "growth" | "pro" | "enterprise";
  limits: {
    max_agents: number | null;
    max_events_per_month: number | null;
    retention_days: number | null;
    custom_rules: boolean;
    compliance_export: boolean;
  };
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const api = new ApiClient();
