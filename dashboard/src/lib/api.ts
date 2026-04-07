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
      throw new ApiError(res.status, body.detail || "Request failed", body.code);
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

  // Alerts
  async getAlertConfig(): Promise<AlertConfig> {
    return this.request("/api/v1/alerts");
  }

  async updateAlertConfig(data: {
    slack_webhook_url?: string;
    alert_emails?: string[];
    webhook_url?: string;
    webhook_headers?: Record<string, string>;
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
    channel: "slack" | "email" | "webhook" = "slack"
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
    config: Record<string, { trigger_threshold?: number; enabled?: boolean }>
  ): Promise<DetectorConfig> {
    return this.request("/api/v1/detector-config", {
      method: "PUT",
      body: JSON.stringify(config),
    });
  }

  async resetDetectorConfig(): Promise<void> {
    return this.request("/api/v1/detector-config", { method: "DELETE" });
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
  min_severity: string;
  enabled: boolean;
}

export interface DetectorEntry {
  trigger_threshold: number;
  enabled: boolean;
  is_default: boolean;
}

export interface DetectorConfig {
  detectors: Record<string, DetectorEntry>;
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
