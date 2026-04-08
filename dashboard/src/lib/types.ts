export type Severity = "critical" | "high" | "medium" | "low";
export type IncidentStatus = "open" | "acknowledged" | "resolved" | "dismissed";

export interface Org {
  id: string;
  name: string;
  clerk_org_id: string;
  stripe_customer_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Agent {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  baseline: Record<string, unknown> | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  health_score: number | null;
  health_grade: "A" | "B" | "C" | "D" | "F" | null;
  health_components: {
    triggered_detections_7d: number;
    open_incidents: number;
    critical_incidents_30d: number;
    anomaly_score: number;
  } | null;
}

export interface AgentEvent {
  id: string;
  agent_id: string;
  session_id: string | null;
  timestamp: string;
  prompt: string | null;
  response: string | null;
  model: string | null;
  tool_calls: Record<string, unknown>[] | null;
  latency_ms: number | null;
  token_count: number | null;
  metadata: Record<string, unknown> | null;
}

export interface Detection {
  id: string;
  event_id: string;
  incident_id: string | null;
  detector: string;
  severity: Severity;
  confidence: number;
  reason: string;
  triggered: boolean;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface Incident {
  id: string;
  org_id: string;
  agent_id: string;
  title: string;
  severity: Severity;
  status: IncidentStatus;
  resolved_at: string | null;
  metadata: Record<string, unknown> | null;
  detections: Detection[];
  created_at: string;
  updated_at: string;
}

export interface Policy {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  allowed_tools: string[] | null;
  blocked_tools: string[] | null;
  allowed_domains: string[] | null;
  blocked_domains: string[] | null;
  max_token_budget: number | null;
  forbidden_patterns: string[] | null;
  custom_rules: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface ApiKey {
  id: string;
  org_id: string;
  name: string;
  key_prefix: string;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiKeyCreated extends ApiKey {
  raw_key: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface AuditEntry {
  id: string;
  org_id: string;
  actor_type: string;
  actor_id: string | null;
  actor_label: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}
