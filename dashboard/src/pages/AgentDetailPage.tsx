import { useMemo, useState } from "react";
import { useParams, useNavigate } from "@tanstack/react-router";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Sparkline } from "@/components/charts/Sparkline";
import { DetectorBreakdown } from "@/components/charts/DetectorBreakdown";
import { EventDetailModal } from "@/components/EventDetailModal";
import { useAgent, useDeleteAgent } from "@/hooks/useAgents";
import type { AgentEvent } from "@/lib/types";
import { useEvents } from "@/hooks/useEvents";
import { useIncidents } from "@/hooks/useIncidents";
import { useAgentEventStream } from "@/hooks/useEventStream";
import { Button } from "@/components/ui/button";
import { Activity, Clock, Cpu, Zap } from "lucide-react";

export function AgentDetailPage() {
  const { agentId } = useParams({ from: "/agents/$agentId" });
  const navigate = useNavigate();
  const [selectedEvent, setSelectedEvent] = useState<AgentEvent | null>(null);
  const { data: agent, isLoading: agentLoading } = useAgent(agentId);
  const deleteAgent = useDeleteAgent();
  const {
    data: eventData,
    isLoading: eventsLoading,
    hasNextPage: hasMoreEvents,
    fetchNextPage: fetchMoreEvents,
    isFetchingNextPage: loadingMoreEvents,
  } = useEvents(agentId);
  const { events: liveEvents, connected } = useAgentEventStream(agentId);

  const { data: incidentData } = useIncidents();
  const events = useMemo(
    () => eventData?.pages.flatMap((p) => p.events) ?? [],
    [eventData]
  );
  const displayEvents = liveEvents.length > 0 ? liveEvents : events;

  // Filter incidents for this agent
  const agentIncidents = useMemo(
    () => (incidentData?.pages.flatMap((p) => p.incidents) ?? []).filter((i) => i.agent_id === agentId),
    [incidentData, agentId]
  );

  // Sparkline data from recent events (newest last for chart direction)
  const latencyData = useMemo(
    () => displayEvents.filter((e) => e.latency_ms != null).map((e) => e.latency_ms!).reverse(),
    [displayEvents]
  );
  const tokenData = useMemo(
    () => displayEvents.filter((e) => e.token_count != null).map((e) => e.token_count!).reverse(),
    [displayEvents]
  );

  if (agentLoading) {
    return (
      <div>
        <Header title="Loading..." />
        <div className="p-6">
          <p className="text-sm text-muted-foreground">Loading agent details...</p>
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div>
        <Header title="Agent Not Found" />
        <div className="p-6">
          <p className="text-sm text-muted-foreground">This agent does not exist.</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <Header
        title={agent.name}
        description={agent.description || `Agent ID: ${agent.id}`}
        actions={
          <div className="flex items-center gap-3">
            <Button
              size="sm"
              variant="ghost"
              className="text-red-400 hover:text-red-300 hover:bg-red-950/50"
              onClick={() => {
                if (confirm("Delete this agent? This cannot be undone.")) {
                  deleteAgent.mutate(agentId, {
                    onSuccess: () => navigate({ to: "/agents" }),
                  });
                }
              }}
            >
              Delete
            </Button>
            <div
              className={`h-2 w-2 rounded-full ${connected ? "bg-green-500" : "bg-zinc-500"}`}
            />
            <span className="text-xs text-muted-foreground">
              {connected ? "Live" : "Disconnected"}
            </span>
          </div>
        }
      />

      <div className="space-y-6 p-6">
        {/* Agent Stats */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardContent className="flex items-center gap-3 p-4">
              <Activity className="h-5 w-5 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">Status</p>
                <p className="font-medium">{agent.is_active ? "Active" : "Inactive"}</p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <Zap className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="text-xs text-muted-foreground">Tokens</p>
                  <p className="font-medium">{events.length} events</p>
                </div>
              </div>
              <Sparkline data={tokenData} color="#3b82f6" />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <Clock className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="text-xs text-muted-foreground">Latency</p>
                  <p className="font-medium">
                    {events[0]?.latency_ms != null ? `${events[0].latency_ms}ms` : "—"}
                  </p>
                </div>
              </div>
              <Sparkline data={latencyData} color="#f97316" />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex items-center gap-3 p-4">
              <Cpu className="h-5 w-5 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">Model</p>
                <p className="font-medium">{events[0]?.model ?? "—"}</p>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Baseline Info — establishing state */}
        {!agent.baseline && (() => {
          const MIN_EVENTS = 20;
          const progress = Math.min(events.length, MIN_EVENTS);
          const pct = Math.round((progress / MIN_EVENTS) * 100);
          return (
            <Card>
              <CardHeader>
                <CardTitle>Behavioral Baseline</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="mb-3 text-sm text-muted-foreground">
                  Establishing baseline — {progress} of {MIN_EVENTS} events recorded.
                  {progress < MIN_EVENTS &&
                    " The baseline auto-generates once enough events are collected."}
                </p>
                <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                  <div
                    className="h-full bg-blue-500 transition-all"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </CardContent>
            </Card>
          );
        })()}

        {/* Baseline Info */}
        {agent.baseline && (() => {
          const baseline = agent.baseline;
          const avgTokens = baseline.avg_token_count as number;
          const stdTokens = (baseline.std_token_count as number) ?? 0;
          const avgLatency = baseline.avg_latency_ms as number;
          const stdLatency = (baseline.std_latency_ms as number) ?? 0;
          const avgToolCalls = (baseline.avg_tool_calls as number) ?? 0;
          const computedAt = baseline.computed_at as string | undefined;
          const eventCount = baseline.event_count as number;
          const currentEventCount = events.length;

          let staleness: { label: string; stale: boolean } | null = null;
          if (computedAt) {
            const ageMs = Date.now() - new Date(computedAt).getTime();
            const ageDays = Math.floor(ageMs / (1000 * 60 * 60 * 24));
            const ageHours = Math.floor(ageMs / (1000 * 60 * 60));
            const label =
              ageDays > 0 ? `${ageDays}d ago` : ageHours > 0 ? `${ageHours}h ago` : "just now";
            // Stale if computed >7d ago OR if event count has grown >50% since computation
            const grewSignificantly =
              currentEventCount > eventCount && currentEventCount > eventCount * 1.5;
            staleness = { label, stale: ageDays > 7 || grewSignificantly };
          }

          return (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0">
                <div>
                  <CardTitle>Behavioral Baseline</CardTitle>
                  {computedAt && staleness && (
                    <p
                      className={`mt-1 text-xs ${staleness.stale ? "text-amber-400" : "text-muted-foreground"}`}
                    >
                      Computed {staleness.label}
                      {staleness.stale && " — stale, consider recomputing"}
                    </p>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
                  <div>
                    <p className="text-xs text-muted-foreground">Avg Tokens</p>
                    <p className="text-lg font-semibold">{Math.round(avgTokens)}</p>
                    <p className="text-xs text-muted-foreground">±{Math.round(stdTokens)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Avg Latency</p>
                    <p className="text-lg font-semibold">{Math.round(avgLatency)}ms</p>
                    <p className="text-xs text-muted-foreground">±{Math.round(stdLatency)}ms</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Avg Tool Calls</p>
                    <p className="text-lg font-semibold">{avgToolCalls.toFixed(1)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Known Models</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {((baseline.known_models as string[]) ?? []).map((m) => (
                        <span key={m} className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                          {m}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Events Analyzed</p>
                    <p className="text-lg font-semibold">{eventCount}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })()}

        {/* Event Timeline */}
        <Card>
          <CardHeader>
            <CardTitle>Event Timeline</CardTitle>
          </CardHeader>
          <CardContent>
            {eventsLoading ? (
              <p className="text-sm text-muted-foreground">Loading events...</p>
            ) : displayEvents.length === 0 ? (
              <p className="text-sm text-muted-foreground">No events recorded yet.</p>
            ) : (
              <div className="space-y-3">
                {displayEvents.map((event) => (
                  <div
                    key={event.id}
                    className="cursor-pointer rounded-md border border-border p-3 transition-colors hover:bg-secondary/50"
                    onClick={() => setSelectedEvent(event)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-muted-foreground">
                          {new Date(event.timestamp).toLocaleTimeString()}
                        </span>
                        {event.model && (
                          <span className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                            {event.model}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 text-xs text-muted-foreground">
                        {event.latency_ms != null && <span>{event.latency_ms}ms</span>}
                        {event.token_count != null && <span>{event.token_count} tokens</span>}
                      </div>
                    </div>
                    {event.prompt && (
                      <p className="mt-2 text-sm text-muted-foreground line-clamp-2">
                        {event.prompt}
                      </p>
                    )}
                    {event.tool_calls && event.tool_calls.length > 0 && (
                      <div className="mt-2 flex gap-1">
                        {event.tool_calls.map((tc, i) => (
                          <span
                            key={i}
                            className="rounded bg-secondary px-1.5 py-0.5 text-xs font-mono"
                          >
                            {(tc as Record<string, string>).name ?? "tool"}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                {hasMoreEvents && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full"
                    onClick={() => fetchMoreEvents()}
                    disabled={loadingMoreEvents}
                  >
                    {loadingMoreEvents ? "Loading..." : "Load more events"}
                  </Button>
                )}
              </div>
            )}
          </CardContent>
        </Card>
        {/* Detection Breakdown */}
        {agentIncidents.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Detection Breakdown</CardTitle>
            </CardHeader>
            <CardContent>
              <DetectorBreakdown incidents={agentIncidents} />
            </CardContent>
          </Card>
        )}
      </div>

      {selectedEvent && (
        <EventDetailModal
          event={selectedEvent}
          onClose={() => setSelectedEvent(null)}
        />
      )}
    </div>
  );
}
