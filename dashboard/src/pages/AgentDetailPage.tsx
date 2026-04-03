import { useMemo } from "react";
import { useParams } from "@tanstack/react-router";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Sparkline } from "@/components/charts/Sparkline";
import { DetectorBreakdown } from "@/components/charts/DetectorBreakdown";
import { useAgent, useDeleteAgent } from "@/hooks/useAgents";
import { useNavigate } from "@tanstack/react-router";
import { useEvents } from "@/hooks/useEvents";
import { useIncidents } from "@/hooks/useIncidents";
import { useAgentEventStream } from "@/hooks/useEventStream";
import { Button } from "@/components/ui/button";
import { Activity, Clock, Cpu, Zap } from "lucide-react";

export function AgentDetailPage() {
  const { agentId } = useParams({ from: "/agents/$agentId" });
  const navigate = useNavigate();
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
                    className="rounded-md border border-border p-3"
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
    </div>
  );
}
