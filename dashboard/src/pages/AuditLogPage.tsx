import { useState } from "react";
import { Header } from "@/components/Header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAuditLog } from "@/hooks/useAuditLog";
import type { AuditEntry } from "@/lib/types";
import { Activity, User, Key, Server } from "lucide-react";

const ACTION_OPTIONS = [
  { value: "", label: "All actions" },
  { value: "incident.acknowledged", label: "Incident acknowledged" },
  { value: "incident.resolved", label: "Incident resolved" },
  { value: "incident.dismissed", label: "Incident dismissed" },
  { value: "api_key.created", label: "API key created" },
  { value: "api_key.revoked", label: "API key revoked" },
  { value: "policy.created", label: "Policy created" },
  { value: "policy.updated", label: "Policy updated" },
  { value: "policy.deleted", label: "Policy deleted" },
  { value: "alert_config.updated", label: "Alert config updated" },
  { value: "alert_config.deleted", label: "Alert config deleted" },
  { value: "detector_config.updated", label: "Detector tuning updated" },
  { value: "detector_config.reset", label: "Detector tuning reset" },
  { value: "baseline.recomputed", label: "Baseline recomputed" },
] as const;

function ActorIcon({ type }: { type: string }) {
  if (type === "user") return <User className="h-3 w-3" />;
  if (type === "api_key") return <Key className="h-3 w-3" />;
  return <Server className="h-3 w-3" />;
}

function actionColor(action: string): string {
  if (action.includes("resolved")) return "text-green-400";
  if (action.includes("dismissed")) return "text-zinc-400";
  if (action.includes("revoked")) return "text-red-400";
  if (action.includes("created")) return "text-blue-400";
  if (action.includes("acknowledged")) return "text-yellow-400";
  return "text-foreground";
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  const details = entry.details ?? {};

  return (
    <div className="flex items-start gap-3 border-b border-border py-3 last:border-0">
      <div className="mt-1 flex h-6 w-6 items-center justify-center rounded-full bg-secondary">
        <ActorIcon type={entry.actor_type} />
      </div>
      <div className="flex-1 space-y-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-medium text-foreground">
            {entry.actor_label || entry.actor_id || entry.actor_type}
          </span>
          <span className={`font-mono text-xs ${actionColor(entry.action)}`}>
            {entry.action}
          </span>
          {entry.resource_type && (
            <Badge variant="outline" className="text-xs">
              {entry.resource_type}
            </Badge>
          )}
        </div>
        {Object.keys(details).length > 0 && (
          <p className="text-xs text-muted-foreground">
            {Object.entries(details)
              .map(([k, v]) => `${k}: ${String(v)}`)
              .join(" · ")}
          </p>
        )}
      </div>
      <span className="whitespace-nowrap text-xs text-muted-foreground">
        {new Date(entry.created_at).toLocaleString()}
      </span>
    </div>
  );
}

export function AuditLogPage() {
  const [actionFilter, setActionFilter] = useState("");
  const { data, isLoading, hasNextPage, fetchNextPage, isFetchingNextPage } = useAuditLog(
    actionFilter ? { action: actionFilter } : undefined
  );

  const entries = data?.pages.flatMap((p) => p.entries) ?? [];

  return (
    <div>
      <Header
        title="Audit Log"
        description="Append-only record of who did what, for compliance and forensics."
      />

      <div className="space-y-4 p-6">
        <div className="flex flex-wrap gap-2">
          {ACTION_OPTIONS.map((opt) => (
            <Button
              key={opt.value}
              size="sm"
              variant={actionFilter === opt.value ? "secondary" : "ghost"}
              onClick={() => setActionFilter(opt.value)}
              className="text-xs"
            >
              {opt.label}
            </Button>
          ))}
        </div>

        <Card>
          <CardContent className="p-4">
            {isLoading ? (
              <p className="text-sm text-muted-foreground">Loading audit log...</p>
            ) : entries.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12">
                <Activity className="mb-4 h-12 w-12 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">No audit events recorded yet.</p>
                <p className="text-xs text-muted-foreground">
                  Actions like incident status changes and API key operations appear here.
                </p>
              </div>
            ) : (
              <div>
                {entries.map((entry) => (
                  <AuditRow key={entry.id} entry={entry} />
                ))}
                {hasNextPage && (
                  <Button
                    variant="ghost"
                    className="mt-4 w-full"
                    onClick={() => fetchNextPage()}
                    disabled={isFetchingNextPage}
                  >
                    {isFetchingNextPage ? "Loading..." : "Load more"}
                  </Button>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
