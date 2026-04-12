import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Link } from "@tanstack/react-router";
import { CheckCircle, AlertTriangle, XCircle } from "lucide-react";

const STATUS_CONFIG = {
  healthy: { icon: CheckCircle, color: "text-emerald-400", bg: "bg-emerald-500/15", label: "Healthy" },
  stale: { icon: AlertTriangle, color: "text-amber-400", bg: "bg-amber-500/15", label: "Stale" },
  silent: { icon: XCircle, color: "text-red-400", bg: "bg-red-500/15", label: "Silent" },
} as const;

export function SDKHealthPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["sdk-health"],
    queryFn: () => api.getSDKHealth(),
    refetchInterval: 30_000,
  });

  return (
    <div>
      <Header
        title="SDK Health"
        description="Monitor SDK integration status across all agents. Stale agents haven't sent events in 3+ hours."
      />
      <div className="space-y-6 p-6">
        {isLoading || !data ? (
          <p className="text-sm text-muted-foreground">Loading SDK health...</p>
        ) : (
          <>
            {/* Summary */}
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground">Total</p>
                  <p className="text-2xl font-bold">{data.total}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground">Healthy</p>
                  <p className="text-2xl font-bold text-emerald-400">{data.healthy}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground">Stale</p>
                  <p className="text-2xl font-bold text-amber-400">{data.stale}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground">Silent</p>
                  <p className="text-2xl font-bold text-red-400">{data.silent}</p>
                </CardContent>
              </Card>
            </div>

            {/* Agent list */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Integration Status</CardTitle>
              </CardHeader>
              <CardContent>
                {data.agents.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No agents found.</p>
                ) : (
                  <div className="divide-y divide-border">
                    {data.agents.map((agent) => {
                      const cfg = STATUS_CONFIG[agent.status] || STATUS_CONFIG.silent;
                      const Icon = cfg.icon;
                      const lastEvent = agent.last_event_at
                        ? new Date(agent.last_event_at).toLocaleString()
                        : "Never";
                      return (
                        <Link
                          key={agent.id}
                          to="/agents/$agentId"
                          params={{ agentId: agent.id }}
                          className="flex items-center justify-between py-3 px-2 rounded transition-colors hover:bg-secondary/30"
                        >
                          <div className="flex items-center gap-3">
                            <Icon className={`h-4 w-4 ${cfg.color}`} />
                            <div>
                              <span className="text-sm font-medium">{agent.name}</span>
                              <p className="text-xs text-muted-foreground">
                                Last event: {lastEvent}
                                {agent.wrapper_type && ` · ${agent.wrapper_type}`}
                                {agent.sdk_version && ` · v${agent.sdk_version}`}
                              </p>
                            </div>
                          </div>
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${cfg.bg} ${cfg.color}`}>
                            {cfg.label}
                          </span>
                        </Link>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
