import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Link } from "@tanstack/react-router";
import { HealthScoreBadge } from "@/components/HealthScoreBadge";

const GRADE_COLORS: Record<string, string> = {
  A: "bg-emerald-500",
  B: "bg-lime-500",
  C: "bg-yellow-500",
  D: "bg-orange-500",
  F: "bg-red-500",
  "?": "bg-zinc-500",
};

export function FleetOverviewPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["fleet-overview"],
    queryFn: () => api.getFleetOverview(),
  });

  return (
    <div>
      <Header
        title="Fleet Overview"
        description="Compare all agents by health score, grade, and status."
      />
      <div className="space-y-6 p-6">
        {isLoading || !data ? (
          <p className="text-sm text-muted-foreground">Loading fleet data...</p>
        ) : (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground">Total Agents</p>
                  <p className="text-2xl font-bold">{data.total_agents}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground">Avg Score</p>
                  <p className="text-2xl font-bold">
                    {data.avg_health_score != null ? data.avg_health_score : "—"}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground">Healthy (A/B)</p>
                  <p className="text-2xl font-bold text-emerald-400">
                    {(data.grade_distribution["A"] || 0) + (data.grade_distribution["B"] || 0)}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground">Needs Attention</p>
                  <p className="text-2xl font-bold text-red-400">
                    {(data.grade_distribution["D"] || 0) + (data.grade_distribution["F"] || 0)}
                  </p>
                </CardContent>
              </Card>
            </div>

            {/* Grade distribution bar */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Grade Distribution</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex h-6 overflow-hidden rounded-full">
                  {["A", "B", "C", "D", "F"].map((grade) => {
                    const count = data.grade_distribution[grade] || 0;
                    if (count === 0) return null;
                    const pct = (count / data.total_agents) * 100;
                    return (
                      <div
                        key={grade}
                        className={`${GRADE_COLORS[grade]} flex items-center justify-center text-[10px] font-bold text-white`}
                        style={{ width: `${pct}%` }}
                        title={`${grade}: ${count} agents`}
                      >
                        {pct > 8 ? `${grade} (${count})` : ""}
                      </div>
                    );
                  })}
                </div>
                <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
                  {["A", "B", "C", "D", "F"].map((g) => (
                    <span key={g} className="flex items-center gap-1">
                      <span className={`inline-block h-2 w-2 rounded-full ${GRADE_COLORS[g]}`} />
                      {g}: {data.grade_distribution[g] || 0}
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Agent table */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">All Agents</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="divide-y divide-border">
                  {data.agents.map((agent) => (
                    <Link
                      key={agent.id}
                      to="/agents/$agentId"
                      params={{ agentId: agent.id }}
                      className="flex items-center justify-between py-3 transition-colors hover:bg-secondary/30 px-2 rounded"
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-sm font-medium">{agent.name}</span>
                        {!agent.is_active && (
                          <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">
                            Inactive
                          </span>
                        )}
                      </div>
                      <HealthScoreBadge
                        score={agent.health_score}
                        grade={agent.health_grade as "A" | "B" | "C" | "D" | "F" | null}
                        size="sm"
                      />
                    </Link>
                  ))}
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
