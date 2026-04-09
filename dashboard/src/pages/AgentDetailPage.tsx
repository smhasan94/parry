import { useMemo, useState } from "react";
import { Link, useParams, useNavigate } from "@tanstack/react-router";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Sparkline } from "@/components/charts/Sparkline";
import { DetectorBreakdown } from "@/components/charts/DetectorBreakdown";
import { EventDetailModal } from "@/components/EventDetailModal";
import { useAgent, useDeleteAgent, useRecomputeBaseline } from "@/hooks/useAgents";
import type { AgentEvent } from "@/lib/types";
import { useEvents } from "@/hooks/useEvents";
import { useIncidents } from "@/hooks/useIncidents";
import { useAgentEventStream } from "@/hooks/useEventStream";
import { useResourceHistory } from "@/hooks/useAuditLog";
import { Button } from "@/components/ui/button";
import { Activity, Clock, Cpu, Zap, History, Swords } from "lucide-react";
import { useStartRedTeamRun } from "@/hooks/useRedTeam";
import { BaselineDriftTimeline } from "@/components/charts/BaselineDriftTimeline";
import { HealthScoreBadge } from "@/components/HealthScoreBadge";
import { useAgentSessions } from "@/hooks/useSession";
import { EventVolume } from "@/components/charts/EventVolume";
import { ToolCallHeatmap } from "@/components/charts/ToolCallHeatmap";
import { ModelUsageDonut } from "@/components/charts/ModelUsageDonut";
import { AnomalyTrend } from "@/components/charts/AnomalyTrend";
import { useAgentStats, type AgentStatsWindow } from "@/hooks/useAgentStats";
import { cn } from "@/lib/utils";

function HealthComponent({
  label,
  value,
  hurt,
}: {
  label: string;
  value: number | string;
  hurt: boolean;
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={`text-lg font-semibold tabular-nums ${
          hurt ? "text-orange-300" : "text-foreground"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

export function AgentDetailPage() {
  const { agentId } = useParams({ from: "/agents/$agentId" });
  const navigate = useNavigate();
  const [selectedEvent, setSelectedEvent] = useState<AgentEvent | null>(null);
  const [anomaliesOnly, setAnomaliesOnly] = useState(false);
  const [statsWindow, setStatsWindow] = useState<AgentStatsWindow>("30d");
  const { data: stats, isLoading: statsLoading } = useAgentStats(agentId, statsWindow);
  const [showDriftHistory, setShowDriftHistory] = useState(false);
  const { data: agent, isLoading: agentLoading } = useAgent(agentId);
  const deleteAgent = useDeleteAgent();
  const recomputeBaseline = useRecomputeBaseline();
  const startRedTeam = useStartRedTeamRun();
  const {
    data: eventData,
    isLoading: eventsLoading,
    hasNextPage: hasMoreEvents,
    fetchNextPage: fetchMoreEvents,
    isFetchingNextPage: loadingMoreEvents,
  } = useEvents(agentId);
  const { events: liveEvents, connected } = useAgentEventStream(agentId);

  const { data: incidentData } = useIncidents();
  const { data: driftHistory, isLoading: driftLoading } = useResourceHistory(
    "agent",
    agentId,
    showDriftHistory
  );
  const driftEntries = useMemo(
    () =>
      (driftHistory?.entries ?? []).filter((e) => e.action === "baseline.recomputed"),
    [driftHistory]
  );
  const events = useMemo(
    () => eventData?.pages.flatMap((p) => p.events) ?? [],
    [eventData]
  );
  const baseEvents = liveEvents.length > 0 ? liveEvents : events;

  const isAnomalous = useMemo(() => {
    const baseline = agent?.baseline;
    if (!baseline) return () => false;
    const avgT = baseline.avg_token_count as number | undefined;
    const avgL = baseline.avg_latency_ms as number | undefined;
    const known = (baseline.known_models as string[] | undefined) ?? [];
    return (e: AgentEvent) => {
      if (avgT && e.token_count != null && avgT > 0) {
        if (Math.abs((e.token_count - avgT) / avgT) > 0.5) return true;
      }
      if (avgL && e.latency_ms != null && avgL > 0) {
        if (Math.abs((e.latency_ms - avgL) / avgL) > 0.5) return true;
      }
      if (e.model && known.length > 0 && !known.includes(e.model)) return true;
      return false;
    };
  }, [agent?.baseline]);

  const anomalyCount = useMemo(
    () => baseEvents.filter(isAnomalous).length,
    [baseEvents, isAnomalous]
  );
  const displayEvents = anomaliesOnly ? baseEvents.filter(isAnomalous) : baseEvents;

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

  // Per-tool sparkline data: top N tools from the baseline's tool_stats,
  // each series = calls-per-event in chronological order.
  const toolSeries = useMemo(() => {
    const toolStats =
      (agent?.baseline?.tool_stats as
        | Record<string, { avg_calls?: number; total_calls?: number }>
        | undefined) ?? null;
    if (!toolStats) return [] as { name: string; data: number[]; avg: number }[];

    // Pick top 4 tools by total_calls
    const topTools = Object.entries(toolStats)
      .map(([name, stat]) => ({
        name,
        avg: stat.avg_calls ?? 0,
        total: stat.total_calls ?? 0,
      }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 4);

    const ordered = [...displayEvents].reverse(); // oldest → newest
    return topTools.map(({ name, avg }) => ({
      name,
      avg,
      data: ordered.map((e) => {
        if (!e.tool_calls) return 0;
        let n = 0;
        for (const tc of e.tool_calls) {
          if ((tc as Record<string, string>).name === name) n += 1;
        }
        return n;
      }),
    }));
  }, [displayEvents, agent?.baseline]);

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
              disabled={startRedTeam.isPending}
              onClick={() =>
                startRedTeam.mutate({
                  agent_id: agentId,
                  mode: "sandbox",
                })
              }
            >
              <Swords className="h-4 w-4" />
              {startRedTeam.isPending ? "Starting…" : "Red team"}
            </Button>
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
        {/* Health Score */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center justify-between text-base">
              <span>Agent Health</span>
              <HealthScoreBadge
                score={agent.health_score}
                grade={agent.health_grade}
                size="md"
              />
            </CardTitle>
          </CardHeader>
          <CardContent>
            {agent.health_components ? (
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <HealthComponent
                  label="Triggered (7d)"
                  value={agent.health_components.triggered_detections_7d}
                  hurt={agent.health_components.triggered_detections_7d > 0}
                />
                <HealthComponent
                  label="Open Incidents"
                  value={agent.health_components.open_incidents}
                  hurt={agent.health_components.open_incidents > 0}
                />
                <HealthComponent
                  label="Critical (30d)"
                  value={agent.health_components.critical_incidents_30d}
                  hurt={agent.health_components.critical_incidents_30d > 0}
                />
                <HealthComponent
                  label="Anomaly Score"
                  value={agent.health_components.anomaly_score.toFixed(2)}
                  hurt={agent.health_components.anomaly_score > 0.3}
                />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Health score is being computed — refresh in a moment.
              </p>
            )}
          </CardContent>
        </Card>

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
              <Sparkline
                data={tokenData}
                color="#3b82f6"
                baselineMean={agent.baseline?.avg_token_count as number | undefined}
                baselineStd={agent.baseline?.std_token_count as number | undefined}
              />
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
              <Sparkline
                data={latencyData}
                color="#f97316"
                baselineMean={agent.baseline?.avg_latency_ms as number | undefined}
                baselineStd={agent.baseline?.std_latency_ms as number | undefined}
              />
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

        {/* Behavioural Graph */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center justify-between text-base">
              <span>Behavioural Graph</span>
              <div className="flex gap-1 rounded-md border border-border p-0.5">
                {(["7d", "30d", "90d"] as const).map((w) => (
                  <button
                    key={w}
                    onClick={() => setStatsWindow(w)}
                    className={cn(
                      "rounded px-2 py-0.5 text-xs font-medium transition-colors",
                      statsWindow === w
                        ? "bg-secondary text-foreground"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {w}
                  </button>
                ))}
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {statsLoading && !stats ? (
              <p className="text-sm text-muted-foreground">Loading stats…</p>
            ) : !stats ? (
              <p className="text-sm text-muted-foreground">
                No events yet. Install the SDK to start monitoring this agent.
              </p>
            ) : (
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Event Volume
                  </p>
                  <EventVolume data={stats.event_volume} />
                </div>
                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Anomaly Trend
                  </p>
                  <AnomalyTrend data={stats.anomaly_trend} />
                </div>
                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Top Tool Calls
                  </p>
                  <ToolCallHeatmap data={stats.tool_calls} />
                </div>
                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Model Usage
                  </p>
                  <ModelUsageDonut data={stats.model_usage} />
                </div>
              </div>
            )}
          </CardContent>
        </Card>

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
          const quality = (baseline.quality as string | undefined) ?? "high";
          const currentEventCount = events.length;
          const qualityClass =
            quality === "high"
              ? "bg-emerald-500/15 text-emerald-300"
              : quality === "medium"
                ? "bg-amber-500/15 text-amber-300"
                : "bg-red-500/15 text-red-300";
          const qualityHint =
            quality === "low"
              ? "Too few samples — drift alerts suppressed"
              : quality === "medium"
                ? "Usable but std dev may be noisy"
                : "Trusted baseline";

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
                  <div className="flex items-center gap-2">
                    <CardTitle>Behavioral Baseline</CardTitle>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${qualityClass}`}
                      title={qualityHint}
                    >
                      {quality} quality
                    </span>
                  </div>
                  {computedAt && staleness && (
                    <p
                      className={`mt-1 text-xs ${staleness.stale ? "text-amber-400" : "text-muted-foreground"}`}
                    >
                      Computed {staleness.label}
                      {staleness.stale && " — stale, consider recomputing"}
                    </p>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => recomputeBaseline.mutate(agentId)}
                  disabled={recomputeBaseline.isPending}
                >
                  {recomputeBaseline.isPending ? "Recomputing..." : "Recompute"}
                </Button>
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

        {/* Baseline drift history */}
        {agent.baseline && (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <History className="h-4 w-4" />
                  Baseline Drift
                </CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">
                  How the baseline has shifted across recomputes (from the audit log).
                </p>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowDriftHistory((v) => !v)}
              >
                {showDriftHistory ? "Hide" : "Show"}
              </Button>
            </CardHeader>
            {showDriftHistory && (
              <CardContent>
                {driftLoading ? (
                  <p className="text-sm text-muted-foreground">Loading drift history...</p>
                ) : driftEntries.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No recompute events recorded yet for this agent. The initial
                    auto-generated baseline does not create an audit entry —
                    drift history begins at the first manual or scheduled recompute.
                  </p>
                ) : (
                  <BaselineDriftTimeline entries={driftEntries} />
                )}
              </CardContent>
            )}
          </Card>
        )}

        {/* Per-tool sparklines */}
        {toolSeries.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Tool Usage</CardTitle>
              <p className="text-xs text-muted-foreground">
                Calls per event for the top {toolSeries.length} tools. Dashed line = baseline avg.
              </p>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {toolSeries.map((series) => (
                  <div key={series.name} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-mono text-foreground">{series.name}</span>
                      <span className="text-muted-foreground">
                        avg {series.avg.toFixed(1)}
                      </span>
                    </div>
                    <Sparkline
                      data={series.data}
                      color="#a855f7"
                      baselineMean={series.avg}
                    />
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Event Timeline */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle>Event Timeline</CardTitle>
            {agent.baseline && (
              <Button
                size="sm"
                variant={anomaliesOnly ? "default" : "ghost"}
                onClick={() => setAnomaliesOnly((v) => !v)}
                disabled={anomalyCount === 0 && !anomaliesOnly}
              >
                {anomaliesOnly ? "Show all" : `Anomalies only (${anomalyCount})`}
              </Button>
            )}
          </CardHeader>
          <CardContent>
            {eventsLoading ? (
              <p className="text-sm text-muted-foreground">Loading events...</p>
            ) : displayEvents.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-8 text-center">
                <Activity className="h-10 w-10 text-muted-foreground" />
                {anomaliesOnly ? (
                  <>
                    <p className="text-sm font-medium">No anomalies in recent events</p>
                    <p className="max-w-sm text-xs text-muted-foreground">
                      Clear the filter to see normal traffic — nothing unusual
                      here means the agent is matching its baseline.
                    </p>
                    <Button
                      size="sm"
                      variant="outline"
                      className="mt-1"
                      onClick={() => setAnomaliesOnly(false)}
                    >
                      Show all events
                    </Button>
                  </>
                ) : (
                  <>
                    <p className="text-sm font-medium">No events recorded yet</p>
                    <p className="max-w-sm text-xs text-muted-foreground">
                      Events show up here as soon as the SDK makes its first
                      LLM call for this agent. Any call wrapped with
                      SentinelOpenAI / SentinelAnthropic / etc. is enough.
                    </p>
                  </>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                {displayEvents.map((event) => {
                  const baseline = agent.baseline;
                  const baselineAvgTokens = baseline?.avg_token_count as number | undefined;
                  const baselineAvgLatency = baseline?.avg_latency_ms as number | undefined;
                  const knownModels = (baseline?.known_models as string[] | undefined) ?? [];

                  const tokenDrift =
                    baselineAvgTokens && event.token_count != null && baselineAvgTokens > 0
                      ? ((event.token_count - baselineAvgTokens) / baselineAvgTokens) * 100
                      : null;
                  const latencyDrift =
                    baselineAvgLatency && event.latency_ms != null && baselineAvgLatency > 0
                      ? ((event.latency_ms - baselineAvgLatency) / baselineAvgLatency) * 100
                      : null;
                  const unknownModel =
                    baseline && event.model && knownModels.length > 0 && !knownModels.includes(event.model);

                  const driftClass = (d: number | null) =>
                    d == null
                      ? "text-muted-foreground"
                      : Math.abs(d) > 50
                      ? "text-amber-400"
                      : "text-muted-foreground";

                  return (
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
                          <span
                            className={`rounded px-1.5 py-0.5 text-xs ${unknownModel ? "bg-amber-950/50 text-amber-300" : "bg-secondary"}`}
                            title={unknownModel ? "Model not in baseline" : undefined}
                          >
                            {event.model}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 text-xs">
                        {event.latency_ms != null && (
                          <span className={driftClass(latencyDrift)}>
                            {event.latency_ms}ms
                            {latencyDrift != null && Math.abs(latencyDrift) > 20 && (
                              <span className="ml-1">
                                ({latencyDrift > 0 ? "+" : ""}
                                {latencyDrift.toFixed(0)}%)
                              </span>
                            )}
                          </span>
                        )}
                        {event.token_count != null && (
                          <span className={driftClass(tokenDrift)}>
                            {event.token_count} tokens
                            {tokenDrift != null && Math.abs(tokenDrift) > 20 && (
                              <span className="ml-1">
                                ({tokenDrift > 0 ? "+" : ""}
                                {tokenDrift.toFixed(0)}%)
                              </span>
                            )}
                          </span>
                        )}
                      </div>
                    </div>
                    {event.prompt && (
                      <p className="mt-2 text-sm text-muted-foreground line-clamp-2">
                        {event.prompt}
                      </p>
                    )}
                    {event.tool_calls && event.tool_calls.length > 0 && (() => {
                      const toolStats =
                        (baseline?.tool_stats as
                          | Record<string, { avg_calls?: number; total_calls?: number }>
                          | undefined) ?? null;
                      // Count per-tool occurrences in this event
                      const counts: Record<string, number> = {};
                      for (const tc of event.tool_calls) {
                        const name = (tc as Record<string, string>).name ?? "tool";
                        counts[name] = (counts[name] ?? 0) + 1;
                      }
                      return (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {Object.entries(counts).map(([name, n]) => {
                            const stat = toolStats?.[name];
                            const unknown = toolStats && !stat;
                            const avg = stat?.avg_calls ?? 0;
                            const excessive = stat && n > Math.max(avg * 3, 3);
                            const cls = unknown
                              ? "bg-red-950/50 text-red-300"
                              : excessive
                                ? "bg-amber-950/50 text-amber-300"
                                : "bg-secondary";
                            const title = unknown
                              ? `'${name}' not in baseline tool set`
                              : excessive
                                ? `${name} called ${n}x (baseline avg ${avg.toFixed(1)})`
                                : undefined;
                            return (
                              <span
                                key={name}
                                className={`rounded px-1.5 py-0.5 text-xs font-mono ${cls}`}
                                title={title}
                              >
                                {name}
                                {n > 1 && <span className="ml-1 opacity-70">×{n}</span>}
                              </span>
                            );
                          })}
                        </div>
                      );
                    })()}
                  </div>
                  );
                })}
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

        {/* Sessions */}
        <AgentSessionsCard agentId={agentId} />
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

function AgentSessionsCard({ agentId }: { agentId: string }) {
  const { data: sessions = [], isLoading } = useAgentSessions(agentId);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Sessions</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading sessions…</p>
        ) : sessions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No sessions recorded yet. Sessions are created automatically when
            the SDK groups related events.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {sessions.map((s) => {
              const started = s.started_at ? new Date(s.started_at) : null;
              const ended = s.ended_at ? new Date(s.ended_at) : null;
              const durationMs =
                started !== null
                  ? (ended?.getTime() ?? Date.now()) - started.getTime()
                  : null;
              return (
                <li
                  key={s.id}
                  className="flex items-center justify-between py-3"
                >
                  <div>
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <span className="font-mono text-xs text-muted-foreground">
                        {s.id.slice(0, 8)}
                      </span>
                      {s.is_live && (
                        <span className="rounded bg-green-950/50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-green-300">
                          Live
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {started ? started.toLocaleString() : "—"} ·{" "}
                      {s.event_count} event{s.event_count === 1 ? "" : "s"}
                      {durationMs !== null && (
                        <>
                          {" · "}
                          {Math.floor(durationMs / 1000)}s
                        </>
                      )}
                    </div>
                  </div>
                  <Link
                    to="/sessions/$sessionId"
                    params={{ sessionId: s.id }}
                  >
                    <Button variant="outline" size="sm">
                      View Replay
                    </Button>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
