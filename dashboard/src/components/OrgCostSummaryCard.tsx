import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useOrgSpend } from "@/hooks/useOrgSpend";
import { DollarSign } from "lucide-react";

function barColor(pct: number): string {
  if (pct >= 90) return "bg-red-500";
  if (pct >= 75) return "bg-yellow-500";
  return "bg-emerald-500";
}

function SpendCell({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-center">
      <div className="text-lg font-bold tabular-nums">${value.toFixed(2)}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

/**
 * Dashboard card showing aggregated spend across all org agents.
 * Displays hour / day / month totals, a top-5 agent breakdown,
 * and a budget utilisation bar if an org-wide monthly cap exists.
 */
export function OrgCostSummaryCard() {
  const { data, isLoading } = useOrgSpend();

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base">Org Cost Summary</CardTitle>
        <DollarSign className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading || !data ? (
          <p className="text-sm text-muted-foreground">Loading spend data…</p>
        ) : (
          <>
            {/* Period totals */}
            <div className="grid grid-cols-3 gap-4">
              <SpendCell label="Last hour" value={data.hour_spend} />
              <SpendCell label="Last 24 h" value={data.day_spend} />
              <SpendCell label="Last 30 d" value={data.month_spend} />
            </div>

            {/* Budget utilisation bar */}
            {data.total_budget_cap !== null && (
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Monthly budget</span>
                  <span className="tabular-nums">
                    ${data.month_spend.toFixed(2)} / ${data.total_budget_cap.toFixed(2)}
                  </span>
                </div>
                <div className="flex h-2 overflow-hidden rounded bg-muted">
                  <div
                    className={barColor(
                      (data.month_spend / data.total_budget_cap) * 100,
                    )}
                    style={{
                      width: `${Math.min(100, (data.month_spend / data.total_budget_cap) * 100)}%`,
                    }}
                  />
                </div>
              </div>
            )}

            {/* Top agents by spend */}
            {data.top_agents.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Top agents (30 d)</p>
                <div className="space-y-1">
                  {data.top_agents.map((a) => (
                    <div
                      key={a.agent_id}
                      className="flex items-center justify-between text-xs"
                    >
                      <span className="truncate text-foreground">{a.agent_name}</span>
                      <span className="ml-2 shrink-0 tabular-nums text-muted-foreground">
                        ${a.month_spend.toFixed(2)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {data.top_agents.length === 0 && (
              <p className="text-xs text-muted-foreground">No spend recorded in the last 30 days.</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
