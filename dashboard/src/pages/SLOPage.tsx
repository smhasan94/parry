import { useQuery } from "@tanstack/react-query";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { api, type SLOStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CheckCircle2, Gauge, Info, MinusCircle, XCircle } from "lucide-react";

/**
 * Internal SLO dashboard.
 *
 * Intentionally *not* a public status page — values come from the
 * in-process Prometheus registry and are cumulative from the last
 * backend restart. The card copy makes that caveat explicit so no
 * one mistakes the numbers for a rolling 30d SLO. For real burn-rate
 * tracking, scrape /metrics with Prometheus and compute in Grafana.
 */

function formatValue(s: SLOStatus): string {
  if (s.value === null) return "—";
  if (s.kind === "ratio_pct") return `${s.value.toFixed(2)}%`;
  return `${(s.value * 1000).toFixed(0)}ms`;
}

function formatTarget(s: SLOStatus): string {
  if (s.kind === "ratio_pct") return `≥ ${s.target.toFixed(2)}%`;
  return `≤ ${(s.target * 1000).toFixed(0)}ms`;
}

function statusIcon(s: SLOStatus) {
  if (s.meets_target === null) {
    return <MinusCircle className="h-5 w-5 text-muted-foreground" />;
  }
  if (s.meets_target) {
    return <CheckCircle2 className="h-5 w-5 text-green-400" />;
  }
  return <XCircle className="h-5 w-5 text-red-400" />;
}

function BudgetBar({ status }: { status: SLOStatus }) {
  const budget = status.budget_remaining_pct;
  if (budget === null) {
    return (
      <p className="text-xs text-muted-foreground">
        No traffic yet — measurement unavailable.
      </p>
    );
  }
  // Render the bar as a 0–100 gauge. Negative = blown budget.
  const clamped = Math.max(0, Math.min(100, budget));
  const label =
    status.kind === "ratio_pct"
      ? `${budget.toFixed(1)}% of error budget remaining`
      : `${budget.toFixed(1)}% headroom vs target`;
  const color =
    budget >= 50 ? "bg-green-500" : budget >= 10 ? "bg-yellow-500" : budget >= 0 ? "bg-orange-500" : "bg-red-500";
  return (
    <div className="space-y-1">
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted/30">
        <div className={cn("h-full", color)} style={{ width: `${clamped}%` }} />
      </div>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

function SLOCard({ status }: { status: SLOStatus }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-base">
          <span>{status.title}</span>
          {statusIcon(status)}
        </CardTitle>
        <CardDescription>{status.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-baseline justify-between">
          <div>
            <p className="text-xs uppercase text-muted-foreground">Current</p>
            <p className="text-2xl font-semibold tabular-nums">
              {formatValue(status)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs uppercase text-muted-foreground">Target</p>
            <p className="text-sm font-medium text-muted-foreground">
              {formatTarget(status)}
            </p>
          </div>
        </div>
        <BudgetBar status={status} />
      </CardContent>
    </Card>
  );
}

export function SLOPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["slo-status"],
    queryFn: () => api.getSLOStatus(),
    refetchInterval: 15_000,
  });

  return (
    <div>
      <Header
        title="SLOs"
        description="Internal service level objectives — at-a-glance health for the on-call."
        actions={
          <span className="flex items-center gap-2 text-xs text-muted-foreground">
            <Gauge className="h-4 w-4" />
            Refreshes every 15s
          </span>
        }
      />

      <div className="space-y-6 p-6">
        {isLoading && (
          <p className="text-sm text-muted-foreground">Loading SLO status…</p>
        )}
        {error && (
          <Card>
            <CardContent className="py-6">
              <p className="text-sm text-red-400">
                Failed to load SLO status. Check backend logs.
              </p>
            </CardContent>
          </Card>
        )}
        {data && (
          <>
            <div className="flex items-start gap-2 rounded-md border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
              <Info className="mt-0.5 h-4 w-4 flex-none" />
              <p>{data.note}</p>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {data.statuses.map((s) => (
                <SLOCard key={s.id} status={s} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
