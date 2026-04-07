import { useState } from "react";
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
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";
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
              <div className="flex flex-col items-center justify-center py-8">
                <Key className="mb-3 h-8 w-8 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">No API keys yet. Create one to get started.</p>
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

        {/* Detector tuning */}
        <DetectorsCard />

        {/* Alerts */}
        <AlertsCard />

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
        server.enabled !== draft.enabled
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
    const payload: Record<string, { trigger_threshold: number; enabled: boolean }> = {};
    for (const [name, draft] of Object.entries(drafts)) {
      payload[name] = {
        trigger_threshold: draft.trigger_threshold,
        enabled: draft.enabled,
      };
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

  const slackEnabled = !!config?.slack_webhook_url;
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

  const handleTest = (channel: "slack" | "email") => {
    testAlert.mutate(channel, {
      onSuccess: () =>
        toast(
          channel === "slack"
            ? "Test sent to Slack"
            : "Test email sent",
          "success"
        ),
    });
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
