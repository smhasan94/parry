import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRole } from "@/hooks/useRole";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/hooks/useApiKeys";
import {
  useAlertConfig,
  useUpdateAlertConfig,
  useDeleteAlertConfig,
  useTestAlert,
} from "@/hooks/useAlerts";
import {
  useDetectorConfig,
  useUpdateDetectorConfig,
  useResetDetectorConfig,
} from "@/hooks/useDetectorConfig";
import {
  useBlockingSettings,
  useResponseScanSettings,
  useUpdateBlockingSettings,
  useUpdateResponseScanSettings,
  type ResponseScanMode,
} from "@/hooks/useBlockingSettings";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";
import { DriftHistogram } from "@/components/charts/DriftHistogram";
import {
  Key,
  Copy,
  ExternalLink,
  Plus,
  Eye,
  EyeOff,
  Ban,
  Bell,
  Send,
  Trash2,
  Mail,
  X,
  Sliders,
  RotateCcw,
  Webhook,
} from "lucide-react";

export function SettingsPage() {
  const { data: apiKeys = [], isLoading } = useApiKeys();
  const createApiKey = useCreateApiKey();
  const revokeApiKey = useRevokeApiKey();

  const [showCreateKey, setShowCreateKey] = useState(false);
  const [keyName, setKeyName] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [showKey, setShowKey] = useState(false);

  const handleCreateKey = () => {
    if (!keyName.trim()) return;
    createApiKey.mutate(keyName.trim(), {
      onSuccess: (data) => {
        setCreatedKey(data.raw_key);
        setKeyName("");
        setShowCreateKey(false);
      },
    });
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  return (
    <div>
      <Header title="Settings" description="Organization settings and API keys" />

      <div className="space-y-6 p-6">
        {/* API Keys */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>API Keys</CardTitle>
                <CardDescription>
                  Manage the API keys used by your SDK instances to authenticate with Parry.
                </CardDescription>
              </div>
              <Button size="sm" onClick={() => setShowCreateKey(!showCreateKey)}>
                <Plus className="h-4 w-4" />
                New Key
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {showCreateKey && (
              <div className="flex items-end gap-4 rounded-md border border-border p-4">
                <div className="flex-1 space-y-2">
                  <label className="text-sm font-medium">Key Name</label>
                  <Input
                    value={keyName}
                    onChange={(e) => setKeyName(e.target.value)}
                    placeholder="e.g. Production SDK"
                  />
                </div>
                <Button onClick={handleCreateKey} disabled={createApiKey.isPending}>
                  {createApiKey.isPending ? "Creating..." : "Create"}
                </Button>
              </div>
            )}

            {createdKey && (
              <div className="rounded-md border border-green-500/30 bg-green-500/10 p-4">
                <p className="text-sm font-medium text-green-400">
                  API key created. Copy it now — it won't be shown again.
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <code className="flex-1 rounded bg-background px-3 py-2 text-sm font-mono">
                    {showKey ? createdKey : createdKey.slice(0, 12) + "\u2022".repeat(30)}
                  </code>
                  <Button size="icon" variant="ghost" onClick={() => setShowKey(!showKey)}>
                    {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                  <Button size="icon" variant="ghost" onClick={() => copyToClipboard(createdKey)}>
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}

            {isLoading ? (
              <p className="text-sm text-muted-foreground">Loading API keys...</p>
            ) : apiKeys.length === 0 && !createdKey ? (
              <div className="flex flex-col items-center gap-2 py-8 text-center">
                <Key className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm font-medium">No API keys yet</p>
                <p className="max-w-sm text-xs text-muted-foreground">
                  API keys authenticate the SDK against this org. The raw
                  key is shown once at creation and then hashed — keep it
                  somewhere safe (a secret manager, not a .env in git).
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {apiKeys.map((key) => (
                  <div
                    key={key.id}
                    className="flex items-center justify-between rounded-md border border-border p-3"
                  >
                    <div className="flex items-center gap-3">
                      <Key className="h-4 w-4 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">{key.name}</p>
                        <p className="font-mono text-xs text-muted-foreground">
                          {key.key_prefix}...
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <Badge variant={key.is_active ? "secondary" : "outline"}>
                        {key.is_active ? "Active" : "Revoked"}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        {key.last_used_at
                          ? `Last used ${new Date(key.last_used_at).toLocaleDateString()}`
                          : "Never used"}
                      </span>
                      {key.is_active && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => revokeApiKey.mutate(key.id)}
                          title="Revoke key"
                        >
                          <Ban className="h-4 w-4 text-muted-foreground" />
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Active blocking mode */}
        <BlockingModeCard />

        {/* Response scanning */}
        <ResponseScanCard />

        {/* Detector tuning */}
        <DetectorsCard />

        {/* Alerts */}
        <AlertsCard />

        {/* Plan + limits */}
        <PlanCard />

        {/* SSO (WorkOS SAML) */}
        <SSOCard />

        {/* Billing */}
        <Card>
          <CardHeader>
            <CardTitle>Billing</CardTitle>
            <CardDescription>
              Manage your subscription and billing details via Stripe.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant="outline"
              onClick={async () => {
                try {
                  const { url } = await api.createBillingPortal(window.location.href);
                  window.location.href = url;
                } catch {
                  toast("Billing portal not available. Contact support.");
                }
              }}
            >
              <ExternalLink className="h-4 w-4" />
              Open Billing Portal
            </Button>
          </CardContent>
        </Card>

        {/* SDK Quick Start */}
        <Card>
          <CardHeader>
            <CardTitle>Quick Start</CardTitle>
            <CardDescription>Get started with the Parry SDK in 2 lines of code.</CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="rounded-md bg-secondary p-4 text-sm font-mono overflow-x-auto">
              <code>{`import parry
parry.init(api_key="sk-parry-...")

# Wrap your OpenAI client
from parry.wrappers.openai import ParryOpenAI
client = ParryOpenAI(agent_id="my-agent")

# Use as normal — Parry monitors in the background
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)`}</code>
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

const SEVERITY_OPTIONS = ["low", "medium", "high", "critical"] as const;

const DETECTOR_LABELS: Record<string, { label: string; description: string }> = {
  prompt_injection: {
    label: "Prompt Injection",
    description: "Detects attempts to override or hijack the agent's system prompt.",
  },
  jailbreak: {
    label: "Jailbreak",
    description: "Catches DAN, developer mode, and other jailbreak prompts.",
  },
  privilege_escalation: {
    label: "Privilege Escalation",
    description: "Flags attempts to grant elevated permissions or bypass auth.",
  },
  tool_misuse: {
    label: "Tool Misuse",
    description: "Detects calls to tools outside the org's policy allowlist.",
  },
  data_exfiltration: {
    label: "Data Exfiltration",
    description: "Catches PII, secrets, and credentials in agent responses.",
  },
  anomaly: {
    label: "Behavioral Anomaly",
    description: "Statistical drift from the agent's baseline (latency, tokens, models).",
  },
  llm_fallback: {
    label: "LLM Fallback",
    description: "Claude-powered classifier that resolves ambiguous detection scores.",
  },
};

interface DraftEntry {
  trigger_threshold: number;
  enabled: boolean;
  sigma_threshold?: number;
}

function DetectorsCard() {
  const { data: config, isLoading } = useDetectorConfig();
  const updateConfig = useUpdateDetectorConfig();
  const resetConfig = useResetDetectorConfig();

  // Local draft state — sliders are responsive without round-tripping every drag
  const [drafts, setDrafts] = useState<Record<string, DraftEntry>>({});

  // Hydrate drafts from server config when it loads or refetches
  const serverDetectors = config?.detectors;
  const draftKeys = Object.keys(drafts);
  if (serverDetectors && draftKeys.length === 0) {
    const initial: Record<string, DraftEntry> = {};
    for (const [name, entry] of Object.entries(serverDetectors)) {
      initial[name] = {
        trigger_threshold: entry.trigger_threshold,
        enabled: entry.enabled,
        sigma_threshold: entry.sigma_threshold,
      };
    }
    // setState during render only when going from empty → seeded
    setDrafts(initial);
  }

  const handleThresholdChange = (name: string, value: number) => {
    setDrafts((d) => {
      const current = d[name];
      if (!current) return d;
      return { ...d, [name]: { ...current, trigger_threshold: value } };
    });
  };

  const handleToggle = (name: string) => {
    setDrafts((d) => {
      const current = d[name];
      if (!current) return d;
      return { ...d, [name]: { ...current, enabled: !current.enabled } };
    });
  };

  const isDirty = (() => {
    if (!serverDetectors) return false;
    for (const name of Object.keys(drafts)) {
      const server = serverDetectors[name];
      const draft = drafts[name];
      if (!server || !draft) continue;
      if (
        server.trigger_threshold !== draft.trigger_threshold ||
        server.enabled !== draft.enabled ||
        (server.sigma_threshold ?? null) !== (draft.sigma_threshold ?? null)
      ) {
        return true;
      }
    }
    return false;
  })();

  const handleSave = () => {
    if (!serverDetectors) return;
    // Only send detectors whose effective config differs from defaults to keep
    // payloads small and the audit log readable.
    const payload: Record<
      string,
      { trigger_threshold: number; enabled: boolean; sigma_threshold?: number }
    > = {};
    for (const [name, draft] of Object.entries(drafts)) {
      const entry: { trigger_threshold: number; enabled: boolean; sigma_threshold?: number } = {
        trigger_threshold: draft.trigger_threshold,
        enabled: draft.enabled,
      };
      if (draft.sigma_threshold != null) {
        entry.sigma_threshold = draft.sigma_threshold;
      }
      payload[name] = entry;
    }
    updateConfig.mutate(payload, {
      onSuccess: () => {
        toast("Detector tuning saved", "success");
      },
    });
  };

  const handleReset = () => {
    if (!confirm("Reset all detectors to Parry defaults?")) return;
    resetConfig.mutate(undefined, {
      onSuccess: () => {
        setDrafts({});
        toast("Reset to defaults", "success");
      },
    });
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Sliders className="h-5 w-5" />
              Detector Tuning
            </CardTitle>
            <CardDescription>
              Adjust trigger thresholds and toggle individual detectors. Lower thresholds
              catch more events; higher thresholds reduce false positives.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading || !serverDetectors ? (
          <p className="text-sm text-muted-foreground">Loading detectors...</p>
        ) : (
          <>
            <div className="space-y-3">
              {Object.entries(drafts).map(([name, draft]) => {
                const meta = DETECTOR_LABELS[name] ?? { label: name, description: "" };
                const server = serverDetectors[name];
                return (
                  <div
                    key={name}
                    className={`rounded-md border border-border p-3 ${
                      draft.enabled ? "" : "opacity-60"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium">{meta.label}</p>
                          {server?.is_default && (
                            <Badge variant="outline" className="text-xs">
                              Default
                            </Badge>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">{meta.description}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleToggle(name)}
                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                          draft.enabled ? "bg-primary" : "bg-secondary"
                        }`}
                        aria-label={`Toggle ${meta.label}`}
                      >
                        <span
                          className={`inline-block h-3 w-3 transform rounded-full bg-background transition-transform ${
                            draft.enabled ? "translate-x-5" : "translate-x-1"
                          }`}
                        />
                      </button>
                    </div>
                    <div className="mt-3 flex items-center gap-3">
                      <span className="w-20 text-xs text-muted-foreground">Sensitivity</span>
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={draft.trigger_threshold}
                        onChange={(e) =>
                          handleThresholdChange(name, parseFloat(e.target.value))
                        }
                        disabled={!draft.enabled}
                        className="h-1 flex-1 cursor-pointer appearance-none rounded-full bg-secondary accent-primary"
                      />
                      <span className="w-12 text-right font-mono text-xs text-muted-foreground">
                        {draft.trigger_threshold.toFixed(2)}
                      </span>
                    </div>
                    {name === "anomaly" && draft.sigma_threshold != null && (
                      <div className="mt-2 flex items-center gap-3">
                        <span
                          className="w-20 text-xs text-muted-foreground"
                          title="How many standard deviations from the baseline mean count as drift"
                        >
                          σ threshold
                        </span>
                        <input
                          type="range"
                          min="1"
                          max="6"
                          step="0.5"
                          value={draft.sigma_threshold}
                          onChange={(e) => {
                            const v = parseFloat(e.target.value);
                            setDrafts((d) => {
                              const cur = d[name];
                              if (!cur) return d;
                              return { ...d, [name]: { ...cur, sigma_threshold: v } };
                            });
                          }}
                          disabled={!draft.enabled}
                          className="h-1 flex-1 cursor-pointer appearance-none rounded-full bg-secondary accent-primary"
                        />
                        <span className="w-12 text-right font-mono text-xs text-muted-foreground">
                          {draft.sigma_threshold.toFixed(1)}σ
                        </span>
                      </div>
                    )}
                    {name === "anomaly" && draft.sigma_threshold != null && (
                      <div className="mt-3 rounded-md border border-border bg-background/50 p-3">
                        <p className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">
                          Drift distribution (live)
                        </p>
                        <DriftHistogram currentSigma={draft.sigma_threshold} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="flex items-center gap-2 pt-2">
              <Button
                size="sm"
                onClick={handleSave}
                disabled={!isDirty || updateConfig.isPending}
              >
                {updateConfig.isPending ? "Saving..." : "Save changes"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={handleReset}
                disabled={resetConfig.isPending}
                className="text-muted-foreground"
              >
                <RotateCcw className="h-4 w-4" />
                Reset to defaults
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function AlertsCard() {
  const { data: config, isLoading } = useAlertConfig();
  const updateConfig = useUpdateAlertConfig();
  const deleteConfig = useDeleteAlertConfig();
  const testAlert = useTestAlert();

  const [webhookUrl, setWebhookUrl] = useState("");
  const [emailInput, setEmailInput] = useState("");
  const [genericWebhookUrl, setGenericWebhookUrl] = useState("");
  const [pagerdutyKey, setPagerdutyKey] = useState("");
  const [opsgenieKey, setOpsgenieKey] = useState("");

  const slackEnabled = !!config?.slack_webhook_url;
  const genericWebhookEnabled = !!config?.webhook_url;
  const pagerdutyEnabled = !!config?.pagerduty_routing_key;
  const opsgenieEnabled = !!config?.opsgenie_api_key;
  const emails = config?.alert_emails ?? [];
  const minSeverity = config?.min_severity ?? "high";

  const handleSaveSlack = () => {
    if (!webhookUrl.trim()) return;
    updateConfig.mutate(
      { slack_webhook_url: webhookUrl.trim() },
      {
        onSuccess: () => {
          setWebhookUrl("");
          toast("Slack webhook saved", "success");
        },
      }
    );
  };

  const handleSaveGenericWebhook = () => {
    if (!genericWebhookUrl.trim()) return;
    updateConfig.mutate(
      { webhook_url: genericWebhookUrl.trim() },
      {
        onSuccess: () => {
          setGenericWebhookUrl("");
          toast("Webhook saved", "success");
        },
      }
    );
  };

  const handleAddEmail = () => {
    const email = emailInput.trim();
    if (!email) return;
    const next = [...emails, email];
    updateConfig.mutate(
      { alert_emails: next },
      {
        onSuccess: () => {
          setEmailInput("");
          toast("Email added", "success");
        },
      }
    );
  };

  const handleRemoveEmail = (email: string) => {
    updateConfig.mutate(
      { alert_emails: emails.filter((e) => e !== email) },
      { onSuccess: () => toast("Email removed", "success") }
    );
  };

  const handleSeverityChange = (severity: string) => {
    updateConfig.mutate(
      { min_severity: severity },
      { onSuccess: () => toast("Severity threshold updated", "success") }
    );
  };

  const handleTest = (
    channel: "slack" | "email" | "webhook" | "pagerduty" | "opsgenie",
  ) => {
    testAlert.mutate(channel, {
      onSuccess: () => {
        const labels: Record<string, string> = {
          slack: "Test sent to Slack",
          email: "Test email sent",
          webhook: "Test sent to webhook",
          pagerduty: "Test sent to PagerDuty",
          opsgenie: "Test sent to Opsgenie",
        };
        toast(labels[channel] ?? "Test sent", "success");
      },
    });
  };

  const handleSavePagerduty = () => {
    if (!pagerdutyKey.trim()) return;
    updateConfig.mutate(
      { pagerduty_routing_key: pagerdutyKey.trim() },
      {
        onSuccess: () => {
          setPagerdutyKey("");
          toast("PagerDuty routing key saved", "success");
        },
      },
    );
  };

  const handleSaveOpsgenie = () => {
    if (!opsgenieKey.trim()) return;
    updateConfig.mutate(
      { opsgenie_api_key: opsgenieKey.trim() },
      {
        onSuccess: () => {
          setOpsgenieKey("");
          toast("Opsgenie API key saved", "success");
        },
      },
    );
  };

  const handleDisableAll = () => {
    if (!confirm("Disable all alerts? You can re-enable them later.")) return;
    deleteConfig.mutate(undefined, {
      onSuccess: () => toast("All alerts disabled", "success"),
    });
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-5 w-5" />
              Alerts
            </CardTitle>
            <CardDescription>
              Get notified via Slack or email when incidents are detected.
            </CardDescription>
          </div>
          {config?.enabled && (
            <Badge variant="secondary" className="text-green-400">
              Enabled
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : (
          <>
            {/* Severity threshold (shared) */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Notify on severity</label>
              <div className="flex gap-2">
                {SEVERITY_OPTIONS.map((s) => (
                  <Button
                    key={s}
                    size="sm"
                    variant={minSeverity === s ? "secondary" : "ghost"}
                    onClick={() => handleSeverityChange(s)}
                    className="text-xs capitalize"
                  >
                    {s}+
                  </Button>
                ))}
              </div>
            </div>

            {/* Slack channel */}
            <div className="space-y-2 rounded-md border border-border p-4">
              <div className="flex items-center gap-2">
                <Bell className="h-4 w-4" />
                <p className="text-sm font-medium">Slack</p>
                {slackEnabled && (
                  <Badge variant="secondary" className="ml-auto text-xs text-green-400">
                    Configured
                  </Badge>
                )}
              </div>
              {slackEnabled ? (
                <div className="space-y-2">
                  <p className="break-all font-mono text-xs text-muted-foreground">
                    {config?.slack_webhook_url?.slice(0, 60)}...
                  </p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleTest("slack")}
                      disabled={testAlert.isPending}
                    >
                      <Send className="h-4 w-4" />
                      Send Test
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => updateConfig.mutate({ slack_webhook_url: "" })}
                    >
                      Replace
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  <Input
                    type="url"
                    value={webhookUrl}
                    onChange={(e) => setWebhookUrl(e.target.value)}
                    placeholder="https://hooks.slack.com/services/..."
                  />
                  <div className="flex items-center justify-between">
                    <a
                      href="https://api.slack.com/messaging/webhooks"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-muted-foreground underline"
                    >
                      How to create a webhook
                    </a>
                    <Button
                      size="sm"
                      onClick={handleSaveSlack}
                      disabled={updateConfig.isPending || !webhookUrl.trim()}
                    >
                      Save
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {/* Email channel */}
            <div className="space-y-2 rounded-md border border-border p-4">
              <div className="flex items-center gap-2">
                <Mail className="h-4 w-4" />
                <p className="text-sm font-medium">Email</p>
                {emails.length > 0 && (
                  <Badge variant="secondary" className="ml-auto text-xs text-green-400">
                    {emails.length} recipient{emails.length === 1 ? "" : "s"}
                  </Badge>
                )}
              </div>

              {emails.length > 0 && (
                <div className="space-y-1">
                  {emails.map((email) => (
                    <div
                      key={email}
                      className="flex items-center justify-between rounded bg-secondary/50 px-3 py-2 text-sm"
                    >
                      <span className="font-mono">{email}</span>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => handleRemoveEmail(email)}
                        title="Remove"
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex gap-2">
                <Input
                  type="email"
                  value={emailInput}
                  onChange={(e) => setEmailInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddEmail()}
                  placeholder="ops@yourcompany.com"
                />
                <Button
                  size="sm"
                  onClick={handleAddEmail}
                  disabled={updateConfig.isPending || !emailInput.trim()}
                >
                  Add
                </Button>
              </div>

              {emails.length > 0 && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleTest("email")}
                  disabled={testAlert.isPending}
                  className="mt-2"
                >
                  <Send className="h-4 w-4" />
                  Send Test Email
                </Button>
              )}
            </div>

            {/* Generic webhook channel */}
            <div className="space-y-2 rounded-md border border-border p-4">
              <div className="flex items-center gap-2">
                <Webhook className="h-4 w-4" />
                <p className="text-sm font-medium">Webhook</p>
                <span className="text-xs text-muted-foreground">
                  PagerDuty, Opsgenie, Teams, Zapier, custom
                </span>
                {genericWebhookEnabled && (
                  <Badge variant="secondary" className="ml-auto text-xs text-green-400">
                    Configured
                  </Badge>
                )}
              </div>
              {genericWebhookEnabled ? (
                <div className="space-y-2">
                  <p className="break-all font-mono text-xs text-muted-foreground">
                    {config?.webhook_url?.slice(0, 60)}...
                  </p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleTest("webhook")}
                      disabled={testAlert.isPending}
                    >
                      <Send className="h-4 w-4" />
                      Send Test
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => updateConfig.mutate({ webhook_url: "" })}
                    >
                      Replace
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  <Input
                    type="url"
                    value={genericWebhookUrl}
                    onChange={(e) => setGenericWebhookUrl(e.target.value)}
                    placeholder="https://events.pagerduty.com/integration/abc/enqueue"
                  />
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-muted-foreground">
                      Receives a JSON POST with the incident payload.
                    </p>
                    <Button
                      size="sm"
                      onClick={handleSaveGenericWebhook}
                      disabled={updateConfig.isPending || !genericWebhookUrl.trim()}
                    >
                      Save
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {/* PagerDuty channel */}
            <div className="space-y-2 rounded-md border border-border p-4">
              <div className="flex items-center gap-2">
                <Webhook className="h-4 w-4" />
                <p className="text-sm font-medium">PagerDuty</p>
                <a
                  href="https://support.pagerduty.com/docs/services-and-integrations"
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-muted-foreground underline hover:text-foreground"
                >
                  setup docs
                </a>
                {pagerdutyEnabled && (
                  <Badge variant="secondary" className="ml-auto text-xs text-green-400">
                    Configured
                  </Badge>
                )}
              </div>
              {pagerdutyEnabled ? (
                <div className="space-y-2">
                  <p className="font-mono text-xs text-muted-foreground">
                    {config?.pagerduty_routing_key}
                  </p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleTest("pagerduty")}
                      disabled={testAlert.isPending}
                    >
                      <Send className="h-4 w-4" />
                      Send Test
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => updateConfig.mutate({ pagerduty_routing_key: "" })}
                    >
                      Replace
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  <Input
                    type="password"
                    value={pagerdutyKey}
                    onChange={(e) => setPagerdutyKey(e.target.value)}
                    placeholder="PagerDuty Events API v2 integration key"
                  />
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-muted-foreground">
                      Triggered for incidents at or above your severity threshold.
                    </p>
                    <Button
                      size="sm"
                      onClick={handleSavePagerduty}
                      disabled={updateConfig.isPending || !pagerdutyKey.trim()}
                    >
                      Save
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {/* Opsgenie channel */}
            <div className="space-y-2 rounded-md border border-border p-4">
              <div className="flex items-center gap-2">
                <Webhook className="h-4 w-4" />
                <p className="text-sm font-medium">Opsgenie</p>
                <a
                  href="https://support.atlassian.com/opsgenie/docs/api-key-management/"
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-muted-foreground underline hover:text-foreground"
                >
                  setup docs
                </a>
                {opsgenieEnabled && (
                  <Badge variant="secondary" className="ml-auto text-xs text-green-400">
                    Configured
                  </Badge>
                )}
              </div>
              {opsgenieEnabled ? (
                <div className="space-y-2">
                  <p className="font-mono text-xs text-muted-foreground">
                    {config?.opsgenie_api_key}
                  </p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleTest("opsgenie")}
                      disabled={testAlert.isPending}
                    >
                      <Send className="h-4 w-4" />
                      Send Test
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => updateConfig.mutate({ opsgenie_api_key: "" })}
                    >
                      Replace
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  <Input
                    type="password"
                    value={opsgenieKey}
                    onChange={(e) => setOpsgenieKey(e.target.value)}
                    placeholder="Opsgenie API integration key"
                  />
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-muted-foreground">
                      Alerts are tagged with severity and use P1–P5 priority.
                    </p>
                    <Button
                      size="sm"
                      onClick={handleSaveOpsgenie}
                      disabled={updateConfig.isPending || !opsgenieKey.trim()}
                    >
                      Save
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {config?.enabled && (
              <Button
                size="sm"
                variant="ghost"
                onClick={handleDisableAll}
                className="text-red-400 hover:text-red-300"
              >
                <Trash2 className="h-4 w-4" />
                Disable all alerts
              </Button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

const SCAN_MODES: { value: ResponseScanMode; label: string; hint: string }[] = [
  {
    value: "off",
    label: "Off",
    hint: "Default. Responses pass through unchanged.",
  },
  {
    value: "redact",
    label: "Redact",
    hint: "Sensitive patterns replaced with [REDACTED:...] placeholders in line.",
  },
  {
    value: "block",
    label: "Block",
    hint: "Responses containing sensitive data are rejected entirely (ParryBlockedError).",
  },
];

function ResponseScanCard() {
  const { data, isLoading } = useResponseScanSettings();
  const update = useUpdateResponseScanSettings();
  const current = (data?.response_scan_mode ?? "off") as ResponseScanMode;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Eye className="h-5 w-5" />
          Response Scanning
        </CardTitle>
        <CardDescription>
          Scan every LLM response for sensitive data (credit cards, SSNs, API
          keys, private keys, AWS credentials) before it reaches your agent.
          Fail-open on any error — a scanner outage never drops a response.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="space-y-2">
            {SCAN_MODES.map((m) => {
              const selected = current === m.value;
              return (
                <button
                  key={m.value}
                  type="button"
                  onClick={() => !selected && update.mutate(m.value)}
                  disabled={update.isPending}
                  className={`flex w-full items-start gap-3 rounded-md border p-3 text-left transition-colors ${
                    selected
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-foreground/30"
                  } ${update.isPending ? "opacity-50" : ""}`}
                >
                  <span
                    className={`mt-0.5 inline-block h-4 w-4 shrink-0 rounded-full border-2 ${
                      selected ? "border-primary bg-primary" : "border-muted-foreground"
                    }`}
                  />
                  <div>
                    <p className="text-sm font-medium">{m.label}</p>
                    <p className="text-xs text-muted-foreground">{m.hint}</p>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function BlockingModeCard() {
  const { data, isLoading } = useBlockingSettings();
  const updateBlocking = useUpdateBlockingSettings();
  const enabled = data?.blocking_enabled ?? false;
  const dirty = updateBlocking.isPending;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Ban className="h-5 w-5" />
          Active Blocking Mode
        </CardTitle>
        <CardDescription>
          When enabled, Parry rejects LLM calls that trigger HIGH or CRITICAL
          rule-based detectors before they reach the model. The SDK raises
          <code className="mx-1 rounded bg-secondary px-1 py-0.5 text-xs">
            ParryBlockedError
          </code>
          which your agent code can catch. Fail-open on any error — Parry
          will never block a call due to its own outage.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="flex items-center justify-between rounded-md border border-border p-3">
            <div>
              <p className="text-sm font-medium">
                {enabled ? "Blocking enabled" : "Observe-only (default)"}
              </p>
              <p className="text-xs text-muted-foreground">
                {enabled
                  ? "HIGH and CRITICAL triggers will be rejected pre-call."
                  : "Detections are logged but never prevent the LLM call."}
              </p>
            </div>
            <button
              type="button"
              onClick={() => updateBlocking.mutate(!enabled)}
              disabled={dirty}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                enabled ? "bg-red-600" : "bg-secondary"
              } ${dirty ? "opacity-50" : ""}`}
              aria-label="Toggle blocking mode"
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-background transition-transform ${
                  enabled ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function formatLimit(value: number | null, unit = ""): string {
  if (value === null) return "Unlimited";
  return `${value.toLocaleString()}${unit ? " " + unit : ""}`;
}

function PlanCard() {
  const { data, isLoading } = useQuery({
    queryKey: ["billing-plan"],
    queryFn: () => api.getPlan(),
  });

  if (isLoading || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Plan</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Loading plan…</p>
        </CardContent>
      </Card>
    );
  }

  const { plan, limits } = data;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Plan</span>
          <Badge variant="secondary" className="uppercase">
            {plan}
          </Badge>
        </CardTitle>
        <CardDescription>
          Your current subscription tier. Quotas are enforced in real time —
          free-tier ingestion returns HTTP 402 once the monthly event limit
          is reached.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Max agents</dt>
            <dd className="font-medium">{formatLimit(limits.max_agents)}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Monthly events</dt>
            <dd className="font-medium">
              {formatLimit(limits.max_events_per_month)}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Retention</dt>
            <dd className="font-medium">
              {limits.retention_days === null
                ? "Unlimited"
                : `${limits.retention_days} days`}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Custom rules</dt>
            <dd className="font-medium">
              {limits.custom_rules ? "Included" : "Upgrade required"}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">
              Compliance export
            </dt>
            <dd className="font-medium">
              {limits.compliance_export ? "Included" : "Upgrade required"}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

function SSOCard() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["sso-status"],
    queryFn: () => api.getSSOStatus(),
  });
  const { can } = useRole();
  const canManage = can("owner");
  const [busy, setBusy] = useState(false);
  const [showProvision, setShowProvision] = useState(false);
  const [workosOrgId, setWorkosOrgId] = useState("");
  const [provisioning, setProvisioning] = useState(false);

  async function handleOpenPortal() {
    setBusy(true);
    try {
      const { url } = await api.generateSSOAdminPortal(window.location.href);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to generate link";
      toast(msg, "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleProvision() {
    if (!workosOrgId.trim()) return;
    setProvisioning(true);
    try {
      await api.ssoProvision(workosOrgId.trim());
      qc.invalidateQueries({ queryKey: ["sso-status"] });
      setShowProvision(false);
      setWorkosOrgId("");
      toast("SSO enabled", "success");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to provision SSO";
      toast(msg, "error");
    } finally {
      setProvisioning(false);
    }
  }

  async function handleDeprovision() {
    setProvisioning(true);
    try {
      await api.ssoProvision(null);
      qc.invalidateQueries({ queryKey: ["sso-status"] });
      toast("SSO disabled", "success");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to disable SSO";
      toast(msg, "error");
    } finally {
      setProvisioning(false);
    }
  }

  if (isLoading || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Single Sign-On (SAML)</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Loading SSO status…</p>
        </CardContent>
      </Card>
    );
  }

  if (!data.configured_on_backend) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Single Sign-On (SAML)</CardTitle>
          <CardDescription>
            Enterprise feature — layer your existing identity provider
            (Okta, Azure AD, Google Workspace, …) on top of Parry's auth.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            SAML SSO is not available on this Parry deployment. Contact
            your Parry admin to enable it.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Single Sign-On (SAML)</span>
          {data.enabled ? (
            <Badge variant="secondary" className="text-xs text-green-400">
              Enabled
            </Badge>
          ) : (
            <Badge variant="outline" className="text-xs">
              Not configured
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          Route your users through your own identity provider (Okta,
          Azure AD, Google Workspace, …). Parry issues a session after
          WorkOS confirms the SAML assertion.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {data.enabled ? (
          <>
            <div className="rounded-md border border-border bg-muted/20 p-3 text-xs">
              <div className="text-muted-foreground">WorkOS organization</div>
              <div className="mt-1 font-mono text-foreground">
                {data.workos_organization_id}
              </div>
            </div>
            {canManage ? (
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleOpenPortal}
                  disabled={busy}
                >
                  {busy ? "Generating link…" : "Open Admin Portal"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={handleDeprovision}
                  disabled={provisioning}
                  className="text-destructive hover:text-destructive"
                >
                  {provisioning ? "Disabling…" : "Disable SSO"}
                </Button>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Owner role required to manage SAML metadata.
              </p>
            )}
          </>
        ) : canManage ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              SSO is available on this deployment but not enabled for your
              organization. Enter your WorkOS organization id to enable SAML.
            </p>
            {showProvision ? (
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <label className="text-xs font-medium">WorkOS Organization ID</label>
                  <Input
                    value={workosOrgId}
                    onChange={(e) => setWorkosOrgId(e.target.value)}
                    placeholder="org_01..."
                    className="mt-1 font-mono text-sm"
                  />
                </div>
                <Button
                  size="sm"
                  onClick={handleProvision}
                  disabled={provisioning || !workosOrgId.trim()}
                >
                  {provisioning ? "Enabling…" : "Enable SSO"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setShowProvision(false)}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setShowProvision(true)}
              >
                Configure SSO
              </Button>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            SSO is available on this deployment but not enabled for your
            organization. Contact an owner to configure it.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
