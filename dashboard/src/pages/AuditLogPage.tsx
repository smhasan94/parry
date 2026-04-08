import { useState } from "react";
import { Header } from "@/components/Header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAuditLog } from "@/hooks/useAuditLog";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";
import type { AuditEntry } from "@/lib/types";
import { Activity, Download, Key, Server, User } from "lucide-react";
import { ErrorState, LoadingState } from "@/components/ui/states";

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

const RECOMPUTE_REASON_OPTIONS = [
  { value: "", label: "All reasons" },
  { value: "manual", label: "Manual (single)" },
  { value: "manual_bulk", label: "Manual (bulk)" },
  { value: "stale_age", label: "Stale by age" },
  { value: "stale_growth", label: "Stale by growth" },
] as const;

export function AuditLogPage() {
  const [actionFilter, setActionFilter] = useState("");
  const [reasonFilter, setReasonFilter] = useState("");
  const [exporting, setExporting] = useState(false);

  // Default the export window to the last 90 days. Admins needing a
  // full SOC 2 year can hit the /audit-log/export endpoint directly
  // with a longer range (backend caps at 400 days).
  async function handleExport(format: "csv" | "json") {
    setExporting(true);
    try {
      const end = new Date();
      const start = new Date();
      start.setDate(end.getDate() - 90);
      const startStr = start.toISOString().slice(0, 10);
      const endStr = end.toISOString().slice(0, 10);
      const blob = await api.downloadAuditLogExport(startStr, endStr, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `parry-audit-${startStr}-${endStr}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast(`Audit log exported (${format.toUpperCase()})`, "success");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Export failed";
      toast(msg, "error");
    } finally {
      setExporting(false);
    }
  }
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useAuditLog(
    actionFilter ? { action: actionFilter } : undefined
  );

  const allEntries = data?.pages.flatMap((p) => p.entries) ?? [];
  const entries =
    actionFilter === "baseline.recomputed" && reasonFilter
      ? allEntries.filter((e) => {
          const r = (e.details as Record<string, unknown> | null | undefined)?.reason;
          // Single-agent recomputes have no reason; treat undefined as "manual"
          if (reasonFilter === "manual") return r == null;
          return r === reasonFilter;
        })
      : allEntries;

  return (
    <div>
      <Header
        title="Audit Log"
        description="Append-only record of who did what, for compliance and forensics."
        actions={
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={exporting}
              onClick={() => handleExport("csv")}
            >
              <Download className="h-4 w-4" />
              {exporting ? "Exporting…" : "Export CSV"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={exporting}
              onClick={() => handleExport("json")}
            >
              <Download className="h-4 w-4" />
              JSON
            </Button>
          </div>
        }
      />

      <div className="space-y-4 p-6">
        <div className="flex flex-wrap gap-2">
          {ACTION_OPTIONS.map((opt) => (
            <Button
              key={opt.value}
              size="sm"
              variant={actionFilter === opt.value ? "secondary" : "ghost"}
              onClick={() => {
                setActionFilter(opt.value);
                if (opt.value !== "baseline.recomputed") setReasonFilter("");
              }}
              className="text-xs"
            >
              {opt.label}
            </Button>
          ))}
        </div>

        {actionFilter === "baseline.recomputed" && (
          <div className="flex flex-wrap items-center gap-2 pl-1">
            <span className="text-xs text-muted-foreground">Reason:</span>
            {RECOMPUTE_REASON_OPTIONS.map((opt) => (
              <Button
                key={opt.value}
                size="sm"
                variant={reasonFilter === opt.value ? "secondary" : "ghost"}
                onClick={() => setReasonFilter(opt.value)}
                className="text-xs"
              >
                {opt.label}
              </Button>
            ))}
          </div>
        )}

        <Card>
          <CardContent className="p-4">
            {isLoading ? (
              <LoadingState label="Loading audit log" />
            ) : isError ? (
              <ErrorState
                error={error}
                title="Couldn't load audit log"
                onRetry={() => refetch()}
              />
            ) : entries.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-12 text-center">
                <Activity className="h-12 w-12 text-muted-foreground" />
                {actionFilter ? (
                  <>
                    <p className="text-sm font-medium">No audit events match this filter</p>
                    <p className="max-w-sm text-xs text-muted-foreground">
                      Try a different action type or clear the filter to see
                      all recent activity.
                    </p>
                    <Button
                      size="sm"
                      variant="outline"
                      className="mt-1"
                      onClick={() => {
                        setActionFilter("");
                        setReasonFilter("");
                      }}
                    >
                      Clear filter
                    </Button>
                  </>
                ) : (
                  <>
                    <p className="text-sm font-medium">No audit events yet</p>
                    <p className="max-w-sm text-xs text-muted-foreground">
                      Every mutation — incident status changes, policy
                      edits, custom rule updates, API key rotations — lands
                      here as an append-only record. The SOC 2 export picks
                      up whatever's visible above.
                    </p>
                  </>
                )}
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
