import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSetBudget, useDeleteBudget } from "@/hooks/useBudget";
import type { AgentBudgetResponse } from "@/lib/api";

interface Props {
  agentId: string;
  existing?: AgentBudgetResponse[];
  onClose: () => void;
}

export function BudgetEditor({ agentId, existing = [], onClose }: Props) {
  const setBudget = useSetBudget();
  const deleteBudget = useDeleteBudget();

  const [period, setPeriod] = useState<"hour" | "day" | "month">("month");
  const [cap, setCap] = useState("");
  const [enabled, setEnabled] = useState(true);

  const current = existing.find(
    (b) => b.agent_id === agentId && b.period === period,
  );

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Budget</CardTitle>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">Period:</label>
          {(["hour", "day", "month"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`rounded border px-2 py-1 text-xs capitalize ${
                period === p
                  ? "border-primary bg-primary/10"
                  : "border-border"
              }`}
            >
              {p}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">$</span>
          <Input
            type="number"
            step="0.01"
            min="0.01"
            value={cap}
            onChange={(e) => setCap(e.target.value)}
            placeholder={current ? String(current.cap_usd) : "100.00"}
            className="w-32"
          />
          <label className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            Enabled
          </label>
        </div>

        {current && (
          <div className="text-xs text-muted-foreground">
            Current {period} cap: ${current.cap_usd.toFixed(2)}{" "}
            {current.enabled ? "(active)" : "(paused)"}
          </div>
        )}

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            disabled={!cap || setBudget.isPending}
            onClick={() =>
              setBudget.mutate(
                {
                  agent_id: agentId,
                  period,
                  cap_usd: Number(cap),
                  enabled,
                },
                { onSuccess: onClose },
              )
            }
          >
            {setBudget.isPending ? "Saving…" : "Save"}
          </Button>
          {current && (
            <Button
              size="sm"
              variant="ghost"
              className="text-red-400"
              disabled={deleteBudget.isPending}
              onClick={() =>
                deleteBudget.mutate(current.id, { onSuccess: onClose })
              }
            >
              Remove
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
