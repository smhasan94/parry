import { useState } from "react";
import { Header } from "@/components/Header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useWebhookEndpoints,
  useCreateWebhookEndpoint,
  useDeleteWebhookEndpoint,
  useTestWebhookEndpoint,
  useWebhookDeliveries,
} from "@/hooks/useWebhooks";
import { useRole } from "@/hooks/useRole";
import { ErrorState, LoadingState } from "@/components/ui/states";
import {
  Webhook,
  Plus,
  Trash2,
  Send,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
  Copy,
} from "lucide-react";
import { toast } from "@/components/ui/toast";
import type { WebhookEndpoint } from "@/lib/types";

const EVENT_TYPES = [
  { id: "detection.triggered", label: "Detection Triggered" },
  { id: "incident.created", label: "Incident Created" },
  { id: "incident.resolved", label: "Incident Resolved" },
  { id: "permission.denied", label: "Permission Denied" },
  { id: "threat_intel.match", label: "Threat Intel Match" },
  { id: "agent.created", label: "Agent Created" },
  { id: "budget.exceeded", label: "Budget Exceeded" },
];

function EndpointCard({ endpoint }: { endpoint: WebhookEndpoint }) {
  const [showDeliveries, setShowDeliveries] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const deleteEndpoint = useDeleteWebhookEndpoint();
  const testEndpoint = useTestWebhookEndpoint();
  const { data: deliveries = [], isLoading: deliveriesLoading } = useWebhookDeliveries(
    showDeliveries ? endpoint.id : "",
  );
  const { can } = useRole();

  return (
    <Card className={!endpoint.is_active ? "opacity-60" : ""}>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm font-medium font-mono">{endpoint.url}</p>
            {endpoint.description && (
              <p className="mt-0.5 text-xs text-muted-foreground">{endpoint.description}</p>
            )}
            <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
              {!endpoint.is_active && (
                <span className="rounded bg-red-100 px-1.5 py-0.5 text-red-700">Disabled</span>
              )}
              {endpoint.failure_count > 0 && (
                <span className="rounded bg-yellow-100 px-1.5 py-0.5 text-yellow-700">
                  {endpoint.failure_count} failures
                </span>
              )}
              {endpoint.last_triggered_at && (
                <span>Last: {new Date(endpoint.last_triggered_at).toLocaleString()}</span>
              )}
            </div>
          </div>
          {can("admin") && (
            <div className="flex gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => testEndpoint.mutate(endpoint.id)}
                disabled={testEndpoint.isPending}
                title="Send test"
              >
                <Send className="h-4 w-4" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => deleteEndpoint.mutate(endpoint.id)}
                disabled={deleteEndpoint.isPending}
                className="text-destructive hover:text-destructive"
                title="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          )}
        </div>

        {/* Event types */}
        <div className="flex flex-wrap gap-1">
          {(endpoint.event_types.length > 0 ? endpoint.event_types : ["all events"]).map((t) => (
            <span key={t} className="rounded bg-primary/10 px-2 py-0.5 text-xs text-primary">
              {t}
            </span>
          ))}
        </div>

        {/* Secret */}
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Secret:</span>
          <code className="rounded bg-muted px-2 py-0.5 font-mono">
            {showSecret ? endpoint.secret : "••••••••••••"}
          </code>
          <button onClick={() => setShowSecret(!showSecret)} className="text-primary text-xs underline">
            {showSecret ? "Hide" : "Show"}
          </button>
          <button
            onClick={() => {
              navigator.clipboard.writeText(endpoint.secret);
              toast("Secret copied", "success");
            }}
          >
            <Copy className="h-3 w-3 text-muted-foreground" />
          </button>
        </div>

        {/* Delivery history toggle */}
        <button
          onClick={() => setShowDeliveries(!showDeliveries)}
          className="flex items-center gap-1 text-xs text-primary"
        >
          {showDeliveries ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          Delivery history
        </button>

        {showDeliveries && (
          <div className="rounded border bg-muted/20 p-2">
            {deliveriesLoading ? (
              <p className="text-xs text-muted-foreground">Loading...</p>
            ) : deliveries.length === 0 ? (
              <p className="text-xs text-muted-foreground">No deliveries yet</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-1">Event</th>
                    <th className="pb-1">Status</th>
                    <th className="pb-1">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {deliveries.slice(0, 20).map((d) => (
                    <tr key={d.id} className="border-b last:border-0">
                      <td className="py-1 font-mono">{d.event_type}</td>
                      <td className="py-1">
                        {d.error ? (
                          <span className="flex items-center gap-1 text-red-600">
                            <XCircle className="h-3 w-3" />
                            {d.error.slice(0, 30)}
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-green-600">
                            <CheckCircle2 className="h-3 w-3" />
                            {d.status_code}
                          </span>
                        )}
                      </td>
                      <td className="py-1 text-muted-foreground">
                        {new Date(d.delivered_at).toLocaleTimeString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function WebhooksPage() {
  const { data: endpoints = [], isLoading, isError, error, refetch } = useWebhookEndpoints();
  const createEndpoint = useCreateWebhookEndpoint();
  const { can } = useRole();
  const canCreate = can("admin");

  const [showCreate, setShowCreate] = useState(false);
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [selectedEvents, setSelectedEvents] = useState<string[]>([]);

  function handleCreate() {
    if (!url.trim()) return;
    createEndpoint.mutate(
      {
        url: url.trim(),
        event_types: selectedEvents,
        description: description.trim() || undefined,
      },
      {
        onSuccess: () => {
          setUrl("");
          setDescription("");
          setSelectedEvents([]);
          setShowCreate(false);
        },
      },
    );
  }

  function toggleEvent(eventId: string) {
    setSelectedEvents((prev) =>
      prev.includes(eventId) ? prev.filter((e) => e !== eventId) : [...prev, eventId],
    );
  }

  return (
    <div>
      <Header
        title="Webhooks"
        description="Receive real-time HTTP notifications for security events"
        actions={
          canCreate ? (
            <Button size="sm" onClick={() => setShowCreate(!showCreate)}>
              <Plus className="mr-1 h-4 w-4" />
              Add Endpoint
            </Button>
          ) : undefined
        }
      />

      <div className="space-y-4 p-6">
        {showCreate && (
          <Card>
            <CardContent className="space-y-3 p-4">
              <div>
                <label className="text-sm font-medium">Endpoint URL *</label>
                <Input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://your-server.com/webhooks/parry"
                  className="mt-1 font-mono"
                />
              </div>
              <div>
                <label className="text-sm font-medium">Description</label>
                <Input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Production alerting pipeline"
                  className="mt-1"
                />
              </div>
              <div>
                <label className="text-sm font-medium">Event Types</label>
                <p className="text-xs text-muted-foreground mb-2">
                  Leave empty to receive all events
                </p>
                <div className="flex flex-wrap gap-2">
                  {EVENT_TYPES.map((evt) => (
                    <button
                      key={evt.id}
                      onClick={() => toggleEvent(evt.id)}
                      className={`rounded border px-2 py-1 text-xs ${
                        selectedEvents.includes(evt.id)
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border text-muted-foreground hover:border-primary"
                      }`}
                    >
                      {evt.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex gap-2">
                <Button onClick={handleCreate} disabled={createEndpoint.isPending || !url.trim()}>
                  {createEndpoint.isPending ? "Creating..." : "Create Endpoint"}
                </Button>
                <Button variant="ghost" onClick={() => setShowCreate(false)}>
                  Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {isLoading ? (
          <LoadingState label="Loading webhook endpoints" />
        ) : isError ? (
          <ErrorState error={error} title="Couldn't load endpoints" onRetry={() => refetch()} />
        ) : endpoints.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <Webhook className="h-12 w-12 text-muted-foreground" />
              <p className="text-sm font-medium">No webhook endpoints configured</p>
              <p className="max-w-sm text-xs text-muted-foreground">
                Add an endpoint to receive real-time HTTP notifications when
                detections fire, incidents are created, or permissions are denied.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {endpoints.map((ep: WebhookEndpoint) => (
              <EndpointCard key={ep.id} endpoint={ep} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
