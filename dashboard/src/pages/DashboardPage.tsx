import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SeverityBadge } from "@/components/ui/badge";
import { SeverityBreakdown } from "@/components/charts/SeverityBreakdown";
import { IncidentTrend } from "@/components/charts/IncidentTrend";
import { useAgents } from "@/hooks/useAgents";
import { useIncidents } from "@/hooks/useIncidents";
import { Bot, AlertTriangle, Shield, Activity } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { HealthScoreBadge } from "@/components/HealthScoreBadge";
import { BlockedEventFeed } from "@/components/BlockedEventFeed";
import type { Agent } from "@/lib/types";

export function DashboardPage() {
  const { data: agents = [], isLoading: agentsLoading } = useAgents();
  const { data: incidentData, isLoading: incidentsLoading } = useIncidents();

  const incidents = incidentData?.pages.flatMap((p) => p.incidents) ?? [];
  const activeAgents = agents.filter((a) => a.is_active).length;
  const openIncidents = incidents.filter((i) => i.status === "open").length;
  const criticalIncidents = incidents.filter((i) => i.severity === "critical").length;

  return (
    <div>
      <Header title="Dashboard" description="AI Agent Runtime Security overview" />

      <div className="space-y-6 p-6">
        {!agentsLoading && !incidentsLoading && agents.length === 0 && (
          <Card className="border-blue-500/30 bg-blue-500/10">
            <CardContent className="flex items-center justify-between p-4">
              <div>
                <p className="font-medium text-blue-400">Welcome to Parry!</p>
                <p className="text-sm text-muted-foreground">Set up your first agent in minutes.</p>
              </div>
              <Link to="/setup">
                <Button size="sm">Get Started</Button>
              </Link>
            </CardContent>
          </Card>
        )}

        {/* Stats Grid */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatsCard
            title="Active Agents"
            value={activeAgents}
            icon={Bot}
            loading={agentsLoading}
          />
          <StatsCard
            title="Open Incidents"
            value={openIncidents}
            icon={AlertTriangle}
            loading={incidentsLoading}
            highlight={openIncidents > 0}
          />
          <StatsCard
            title="Critical Alerts"
            value={criticalIncidents}
            icon={Shield}
            loading={incidentsLoading}
            highlight={criticalIncidents > 0}
          />
          <StatsCard
            title="Total Agents"
            value={agents.length}
            icon={Activity}
            loading={agentsLoading}
          />
        </div>

        {/* Charts */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Incident Trend (7 days)</CardTitle>
            </CardHeader>
            <CardContent>
              <IncidentTrend incidents={incidents} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Severity Breakdown</CardTitle>
            </CardHeader>
            <CardContent>
              <SeverityBreakdown incidents={incidents} />
            </CardContent>
          </Card>
        </div>

        <FleetHealthCard agents={agents} />

        <BlockedEventFeed />

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Agent Grid */}
          <Card>
            <CardHeader>
              <CardTitle>Agents</CardTitle>
            </CardHeader>
            <CardContent>
              {agentsLoading ? (
                <p className="text-sm text-muted-foreground">Loading agents...</p>
              ) : agents.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No agents registered yet. Install the SDK to get started.
                </p>
              ) : (
                <div className="space-y-2">
                  {agents.slice(0, 8).map((agent) => (
                    <Link
                      key={agent.id}
                      to="/agents/$agentId"
                      params={{ agentId: agent.id }}
                      className="flex items-center justify-between rounded-md border border-border p-3 transition-colors hover:bg-secondary/50"
                    >
                      <div className="flex items-center gap-3">
                        <Bot className="h-4 w-4 text-muted-foreground" />
                        <div>
                          <p className="text-sm font-medium">{agent.name}</p>
                          {agent.description && (
                            <p className="text-xs text-muted-foreground">{agent.description}</p>
                          )}
                        </div>
                      </div>
                      <div
                        className={`h-2 w-2 rounded-full ${agent.is_active ? "bg-green-500" : "bg-zinc-500"}`}
                      />
                    </Link>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Recent Incidents */}
          <Card>
            <CardHeader>
              <CardTitle>Recent Incidents</CardTitle>
            </CardHeader>
            <CardContent>
              {incidentsLoading ? (
                <p className="text-sm text-muted-foreground">Loading incidents...</p>
              ) : incidents.length === 0 ? (
                <p className="text-sm text-muted-foreground">No incidents detected. All clear.</p>
              ) : (
                <div className="space-y-2">
                  {incidents.slice(0, 8).map((incident) => (
                    <div
                      key={incident.id}
                      className="flex items-center justify-between rounded-md border border-border p-3"
                    >
                      <div className="flex-1">
                        <p className="text-sm font-medium">{incident.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {new Date(incident.created_at).toLocaleString()}
                        </p>
                      </div>
                      <SeverityBadge severity={incident.severity} />
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function FleetHealthCard({ agents }: { agents: Agent[] }) {
  const scored = agents.filter(
    (a): a is Agent & { health_score: number } => a.health_score !== null,
  );
  const avg =
    scored.length > 0
      ? Math.round(scored.reduce((sum, a) => sum + a.health_score, 0) / scored.length)
      : null;

  const gradeCounts = { A: 0, B: 0, C: 0, D: 0, F: 0 } as Record<string, number>;
  for (const a of scored) {
    if (a.health_grade) gradeCounts[a.health_grade] = (gradeCounts[a.health_grade] ?? 0) + 1;
  }
  const total = scored.length || 1;
  const bars: [string, string][] = [
    ["A", "bg-green-500"],
    ["B", "bg-blue-500"],
    ["C", "bg-yellow-500"],
    ["D", "bg-orange-500"],
    ["F", "bg-red-500"],
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Fleet Health</span>
          <HealthScoreBadge score={avg} size="md" />
        </CardTitle>
      </CardHeader>
      <CardContent>
        {scored.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No health scores yet. Scores are computed for every registered
            agent and refreshed hourly.
          </p>
        ) : (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Average across {scored.length} agent{scored.length === 1 ? "" : "s"}
            </p>
            <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted/30">
              {bars.map(([grade, color]) => {
                const pct = ((gradeCounts[grade] ?? 0) / total) * 100;
                if (pct === 0) return null;
                return (
                  <div
                    key={grade}
                    className={color}
                    style={{ width: `${pct}%` }}
                    title={`${grade}: ${gradeCounts[grade]}`}
                  />
                );
              })}
            </div>
            <div className="flex flex-wrap gap-3 pt-1 text-xs text-muted-foreground">
              {bars.map(([grade]) => (
                <span key={grade}>
                  <span className="font-semibold text-foreground">{grade}</span>{" "}
                  {gradeCounts[grade]}
                </span>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StatsCard({
  title,
  value,
  icon: Icon,
  loading,
  highlight,
}: {
  title: string;
  value: number;
  icon: React.ComponentType<{ className?: string }>;
  loading: boolean;
  highlight?: boolean;
}) {
  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            <p className={`text-2xl font-bold ${highlight ? "text-red-400" : ""}`}>
              {loading ? "..." : value}
            </p>
          </div>
          <Icon className={`h-8 w-8 ${highlight ? "text-red-400" : "text-muted-foreground"}`} />
        </div>
      </CardContent>
    </Card>
  );
}
