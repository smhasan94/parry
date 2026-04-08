import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SeverityBadge } from "@/components/ui/badge";
import { SeverityBreakdown } from "@/components/charts/SeverityBreakdown";
import { IncidentTrend } from "@/components/charts/IncidentTrend";
import { useAgents } from "@/hooks/useAgents";
import { useIncidents } from "@/hooks/useIncidents";
import { Bot, AlertTriangle, Shield, Activity, Sparkles, CheckCircle2 } from "lucide-react";
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
          <FirstRunCard />
        )}

        {/* Everything below the first-run card is only useful once
            there's at least one agent registered. Hiding it on a
            brand new dashboard prevents the "wall of zeros" look. */}
        {!(!agentsLoading && !incidentsLoading && agents.length === 0) && (
        <>
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
        </>
        )}
      </div>
    </div>
  );
}

function FirstRunCard() {
  const installSnippet = `pip install parry

from parry.wrappers.openai import SentinelOpenAI
client = SentinelOpenAI(
    agent_id="support-bot",
    api_key="sk-parry-...",
)`;

  return (
    <div className="space-y-6">
      <Card className="border-primary/40 bg-primary/5">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            Welcome to Parry
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Runtime security for AI agents. Wrap your LLM client with
            the Parry SDK and every call flows through the detection
            engine — prompt injection, tool misuse, behavioural drift,
            all in real time.
          </p>
          <div className="overflow-hidden rounded-md border border-border bg-background/60">
            <div className="flex items-center gap-1.5 border-b border-border px-3 py-1.5 text-[10px] text-muted-foreground">
              <span className="h-2 w-2 rounded-full bg-red-500/70" />
              <span className="h-2 w-2 rounded-full bg-yellow-500/70" />
              <span className="h-2 w-2 rounded-full bg-green-500/70" />
              <span className="ml-2 font-mono">quickstart.py</span>
            </div>
            <pre className="overflow-x-auto px-4 py-3 text-xs text-foreground/90">
              <code>{installSnippet}</code>
            </pre>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/setup">
              <Button size="sm">
                <Sparkles className="h-4 w-4" />
                Guided setup
              </Button>
            </Link>
            <Link to="/settings">
              <Button size="sm" variant="outline">
                Create an API key
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <FeaturePreview
          icon={Shield}
          title="Block dangerous calls"
          body="Rule + LLM detection stops prompt injection and tool misuse before the call fires."
        />
        <FeaturePreview
          icon={Activity}
          title="See every call"
          body="Session replay, behavioural graphs, and live feeds show exactly what your agents are doing."
        />
        <FeaturePreview
          icon={CheckCircle2}
          title="Compliance-ready"
          body="SOC 2 audit export, EU AI Act-shaped PDFs, signed on-prem deploys — all built in."
        />
      </div>
    </div>
  );
}

function FeaturePreview({
  icon: Icon,
  title,
  body,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  body: string;
}) {
  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <Icon className="h-5 w-5 text-primary" />
        <p className="font-medium text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">{body}</p>
      </CardContent>
    </Card>
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
