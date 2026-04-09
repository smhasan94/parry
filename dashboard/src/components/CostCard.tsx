import { useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useAgentSpend, useAgentBudgets } from "@/hooks/useBudget";
import { BudgetEditor } from "@/components/BudgetEditor";
import { useRole } from "@/hooks/useRole";
import { DollarSign } from "lucide-react";

interface Props {
  agentId: string;
}

function barColor(pct: number): string {
  if (pct >= 90) return "bg-red-500";
  if (pct >= 75) return "bg-yellow-500";
  return "bg-emerald-500";
}

/**
 * Mounted on AgentDetailPage below the Health card. Shows current
 * period spend with budget progress bar + edit button.
 */
export function CostCard({ agentId }: Props) {
  const { data: spend } = useAgentSpend(agentId);
  const { data: budgets = [] } = useAgentBudgets(agentId);
  const { can } = useRole();
  const [editing, setEditing] = useState(false);

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-base">Cost</CardTitle>
          {can("admin") && (
            <Button size="sm" variant="ghost" onClick={() => setEditing((v) => !v)}>
              <DollarSign className="h-4 w-4" />
              {editing ? "Close" : "Budget"}
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {spend ? (
            <>
              <div className="grid grid-cols-3 gap-4 text-center">
                <SpendCell label="Hour" value={spend.period_spend.hour} />
                <SpendCell label="Day" value={spend.period_spend.day} />
                <SpendCell label="Month" value={spend.period_spend.month} />
              </div>

              {spend.budgets.length > 0 && (
                <div className="space-y-2">
                  {spend.budgets.map((b) => (
                    <div key={b.period} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="capitalize text-muted-foreground">
                          {b.period} budget
                        </span>
                        <span className="tabular-nums">
                          ${b.spent_usd.toFixed(2)} / ${b.cap_usd.toFixed(2)}
                        </span>
                      </div>
                      <div className="flex h-2 overflow-hidden rounded bg-muted">
                        <div
                          className={barColor(b.pct)}
                          style={{ width: `${Math.min(100, b.pct)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="text-sm text-muted-foreground">
              Loading spend data…
            </div>
          )}
        </CardContent>
      </Card>

      {editing && (
        <BudgetEditor
          agentId={agentId}
          existing={budgets}
          onClose={() => setEditing(false)}
        />
      )}
    </>
  );
}

function SpendCell({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-lg font-bold tabular-nums">${value.toFixed(2)}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}
