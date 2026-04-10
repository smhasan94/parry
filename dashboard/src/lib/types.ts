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

// ── EU AI Act Compliance ────────────────────────────────────────

export type RiskLevel = "minimal" | "limited" | "high" | "unacceptable";
export type FRIAStatus = "not_required" | "missing" | "draft" | "approved" | "stale";
export type ObligationStatus = "green" | "yellow" | "red" | "na";

export interface AISystem {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  risk_level: RiskLevel;
  intended_purpose: string;
  deployer_name: string | null;
  provider_name: string | null;
  provider_contact: string | null;
  deployment_date: string | null;
  retired_date: string | null;
  fria_required: boolean;
  fria_status: FRIAStatus;
  agent_ids: string[];
  annex_iii_category: string | null;
  jurisdiction: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface Supplier {
  id: string;
  system_id: string;
  supplier_name: string;
  model_id: string;
  model_version: string | null;
  first_used_at: string;
  last_used_at: string;
  event_count: number;
  jurisdiction: string | null;
  provider_url: string | null;
}

export interface FRIADocument {
  id: string;
  org_id: string;
  system_id: string;
  version: number;
  status: "draft" | "approved" | "archived";
  content: Record<string, unknown>;
  generated_at: string;
  generated_by: string | null;
  approved_at: string | null;
  approved_by: string | null;
  approver_title: string | null;
  next_review_date: string | null;
}

export interface SeriousIncidentReport {
  id: string;
  org_id: string;
  incident_id: string;
  system_id: string | null;
  deadline_at: string;
  reported_to_authority_at: string | null;
  authority_jurisdiction: string | null;
  report_version: number;
  report_content: Record<string, unknown>;
  created_at: string;
  created_by: string | null;
  days_remaining: number | null;
}

export interface Obligation {
  id: string;
  article: string;
  title: string;
  status: ObligationStatus;
  evidence: Record<string, unknown>;
  remediation: string | null;
}

export interface PostureResponse {
  overall_status: ObligationStatus;
  obligations: Obligation[];
}

// ── Agent Groups ────────────────────────────────────────────────

export interface AgentGroup {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  agent_count: number;
}

// ── Webhook Subscriptions ────────────────────────────────────────

export interface WebhookEndpoint {
  id: string;
  org_id: string;
  url: string;
  secret: string;
  description: string | null;
  event_types: string[];
  is_active: boolean;
  failure_count: number;
  last_triggered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WebhookDelivery {
  id: string;
  endpoint_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  status_code: number | null;
  response_body: string | null;
  error: string | null;
  attempt: number;
  delivered_at: string;
}

// ── Incident Replay ─────────────────────────────────────────────

export interface ReplayAnnotation {
  detections: Array<{
    detector: string;
    severity: string;
    confidence: number;
    reason: string;
    triggered: boolean;
  }>;
  permission_violations: string[];
  threat_intel_matches: string[];
  relevance_score: number;
}

export interface ReplayEvent {
  id: string;
  timestamp: string | null;
  model: string | null;
  prompt_preview: string | null;
  response_preview: string | null;
  prompt?: string | null;
  response?: string | null;
  tool_calls: Record<string, unknown>[] | null;
  token_count: number | null;
  is_trigger: boolean;
  annotations: ReplayAnnotation;
}

export interface IncidentReplay {
  incident: {
    id: string;
    title: string;
    severity: string;
    status: string;
    created_at: string | null;
  };
  trigger_event_id: string | null;
  session_id: string | null;
  total_session_events: number;
  window_size: number;
  events: ReplayEvent[];
}

// ── Threat Intelligence ──────────────────────────────────────────

export interface ThreatIndicator {
  id: string;
  pattern_hash: string;
  detector_source: string;
  category: string;
  severity: string;
  confidence_avg: number;
  sighting_count: number;
  org_count: number;
  first_seen_at: string;
  last_seen_at: string;
  promoted_at: string | null;
  score: number;
  sample_reason: string | null;
}

export interface ThreatFeedStats {
  total_indicators: number;
  active_indicators: number;
  by_category: Record<string, number>;
}

// ── Agent Permissions ────────────────────────────────────────────

export interface AgentPermission {
  id: string;
  org_id: string;
  agent_id: string | null;
  mode: "enforcing" | "dry_run" | "disabled";
  default_action: "allow" | "deny";
  allowed_tools: string[];
  blocked_tools: string[];
  created_at: string;
  updated_at: string;
}

// ── SSO ─────────────────────────────────────────────────────────

export interface SSOStatusResponse {
  enabled: boolean;
  configured_on_backend: boolean;
  workos_organization_id: string | null;
}
