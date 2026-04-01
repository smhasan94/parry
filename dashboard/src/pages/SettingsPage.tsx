import { useState } from "react";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Key, Copy, ExternalLink, Plus, Eye, EyeOff } from "lucide-react";

export function SettingsPage() {
  const [showCreateKey, setShowCreateKey] = useState(false);
  const [keyName, setKeyName] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [showKey, setShowKey] = useState(false);

  // Mock API keys for display — in production these come from the backend
  const apiKeys = [
    {
      id: "1",
      name: "Production SDK",
      key_prefix: "sk-parry-prod",
      is_active: true,
      last_used_at: "2026-03-31T14:22:00Z",
      created_at: "2026-01-15T10:00:00Z",
    },
    {
      id: "2",
      name: "Staging SDK",
      key_prefix: "sk-parry-stg",
      is_active: true,
      last_used_at: null,
      created_at: "2026-02-20T10:00:00Z",
    },
  ];

  const handleCreateKey = () => {
    if (!keyName.trim()) return;
    // In production, this calls the backend
    setCreatedKey("sk-parry-" + Math.random().toString(36).substring(2, 34));
    setKeyName("");
    setShowCreateKey(false);
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
                <Button onClick={handleCreateKey}>Create</Button>
              </div>
            )}

            {createdKey && (
              <div className="rounded-md border border-green-500/30 bg-green-500/10 p-4">
                <p className="text-sm font-medium text-green-400">
                  API key created. Copy it now — it won't be shown again.
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <code className="flex-1 rounded bg-background px-3 py-2 text-sm font-mono">
                    {showKey ? createdKey : "•".repeat(40)}
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
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Billing */}
        <Card>
          <CardHeader>
            <CardTitle>Billing</CardTitle>
            <CardDescription>
              Manage your subscription and billing details via Stripe.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline">
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
