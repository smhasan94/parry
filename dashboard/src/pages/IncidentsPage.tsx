import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { Header } from "@/components/Header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SeverityBadge, Badge } from "@/components/ui/badge";
import { useIncidents, useUpdateIncident } from "@/hooks/useIncidents";
import { useResourceHistory } from "@/hooks/useAuditLog";
import type { IncidentStatus, Severity, AuditEntry } from "@/lib/types";
import { AlertTriangle, CheckCircle, Eye, Film, XCircle, Clock, ChevronDown, ChevronUp } from "lucide-react";
import { AttackChainReplay } from "@/components/AttackChainReplay";
import { ErrorState, LoadingState } from "@/components/ui/states";

const SEVERITY_OPTIONS: (Severity | "all")[] = ["all", "critical", "high", "medium", "low"];
const STATUS_OPTIONS: (IncidentStatus | "all")[] = ["all", "open", "acknowledged", "resolved", "dismissed"];

export function IncidentsPage() {
  const [severityFilter, setSeverityFilter] = useState<Severity | "all">("all");
  const [statusFilter, setStatusFilter] = useState<IncidentStatus | "all">("all");

  const filters = {
    ...(severityFilter !== "all" ? { severity: severityFilter } : {}),
    ...(statusFilter !== "all" ? { status: statusFilter } : {}),
  };

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useIncidents(Object.keys(filters).length > 0 ? filters : undefined);
  const updateIncident = useUpdateIncident();
  const incidents = data?.pages.flatMap((p) => p.incidents) ?? [];
  const [expandedHistory, setExpandedHistory] = useState<Set<string>>(new Set());

  const toggleHistory = (id: string) => {
    setExpandedHistory((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div>
      <Header title="Incidents" description="Security incidents requiring review" />

      <div className="space-y-4 p-6">
        {/* Filters */}
        <div className="flex flex-wrap gap-2">
          <div className="flex items-center gap-1">
            <span className="text-xs text-muted-foreground mr-1">Severity:</span>
            {SEVERITY_OPTIONS.map((s) => (
              <Button
                key={s}
                size="sm"
                variant={severityFilter === s ? "secondary" : "ghost"}
                onClick={() => setSeverityFilter(s)}
                className="text-xs"
              >
                {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
              </Button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <span className="text-xs text-muted-foreground mr-1">Status:</span>
            {STATUS_OPTIONS.map((s) => (
              <Button
                key={s}
                size="sm"
                variant={statusFilter === s ? "secondary" : "ghost"}
                onClick={() => setStatusFilter(s)}
                className="text-xs"
              >
                {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
              </Button>
            ))}
          </div>
        </div>

        {/* Incident List */}
        {isLoading ? (
          <Card>
            <CardContent>
              <LoadingState label="Loading incidents" />
            </CardContent>
          </Card>
        ) : isError ? (
          <Card>
            <CardContent>
              <ErrorState
                error={error}
                title="Couldn't load incidents"
                onRetry={() => refetch()}
              />
            </CardContent>
          </Card>
        ) : incidents.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center gap-2 py-12 text-center">
              <CheckCircle className="h-12 w-12 text-green-500" />
              {severityFilter !== "all" || statusFilter !== "all" ? (
                <>
                  <p className="text-sm font-medium">No incidents match these filters</p>
                  <p className="max-w-sm text-xs text-muted-foreground">
                    Try clearing the severity or status filter to see all
                    incidents.
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    className="mt-2"
                    onClick={() => {
                      setSeverityFilter("all");
                      setStatusFilter("all");
                    }}
                  >
                    Clear filters
                  </Button>
                </>
              ) : (
                <>
                  <p className="text-sm font-medium">No incidents — all clear</p>
                  <p className="max-w-sm text-xs text-muted-foreground">
                    Incidents show up here when the detection engine groups
                    triggered detections into something that needs a human
                    look. A quiet list is a good sign.
                  </p>
                </>
              )}
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {incidents.map((incident) => (
              <Card key={incident.id}>
                <CardContent className="p-4">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <AlertTriangle className="h-4 w-4 text-muted-foreground" />
                        <h3 className="font-medium">{incident.title}</h3>
                      </div>
                      <div className="mt-1 flex items-center gap-2">
                        <SeverityBadge severity={incident.severity} />
                        <Badge variant="outline">{incident.status}</Badge>
                        <span className="text-xs text-muted-foreground">
                          {new Date(incident.created_at).toLocaleString()}
                        </span>
                      </div>
                      {incident.detections.length > 0 && (
                        <div className="mt-2 space-y-1">
                          {incident.detections.map((d) => (
                            <p key={d.id} className="text-xs text-muted-foreground">
                              [{d.detector}] {d.reason} (confidence: {(d.confidence * 100).toFixed(0)}%)
                            </p>
                          ))}
                        </div>
                      )}
                      <button
                        type="button"
                        onClick={() => toggleHistory(incident.id)}
                        className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                      >
                        {expandedHistory.has(incident.id) ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                        History
                      </button>
                      {expandedHistory.has(incident.id) && (
                        <IncidentHistory incidentId={incident.id} />
                      )}
                    </div>
                    <div className="flex gap-1">
                      {(() => {
                        const sessionId = (incident.metadata as { trigger_session_id?: string } | null)
                          ?.trigger_session_id;
                        if (!sessionId) return null;
                        return (
                          <Link
                            to="/sessions/$sessionId"
                            params={{ sessionId }}
                          >
                            <Button size="sm" variant="ghost" title="View session replay">
                              <Film className="h-4 w-4" />
                            </Button>
                          </Link>
                        );
                      })()}
                      <AttackChainReplay incidentId={incident.id} />
                      {incident.status === "open" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            updateIncident.mutate({
                              incidentId: incident.id,
                              data: { status: "acknowledged" },
                            })
                          }
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                      )}
                      {(incident.status === "open" || incident.status === "acknowledged") && (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() =>
                              updateIncident.mutate({
                                incidentId: incident.id,
                                data: { status: "resolved" },
                              })
                            }
                          >
                            <CheckCircle className="h-4 w-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() =>
                              updateIncident.mutate({
                                incidentId: incident.id,
                                data: { status: "dismissed" },
                              })
                            }
                          >
                            <XCircle className="h-4 w-4" />
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
            {hasNextPage && (
              <Button
                variant="ghost"
                className="w-full"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
              >
                {isFetchingNextPage ? "Loading..." : "Load more incidents"}
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const ACTION_LABELS: Record<string, string> = {
  "incident.acknowledged": "acknowledged",
  "incident.resolved": "resolved",
  "incident.dismissed": "dismissed",
};

function IncidentHistory({ incidentId }: { incidentId: string }) {
  const { data, isLoading } = useResourceHistory("incident", incidentId, true);

  if (isLoading) {
    return (
      <p className="mt-2 text-xs text-muted-foreground">Loading history...</p>
    );
  }

  const entries = data?.entries ?? [];
  if (entries.length === 0) {
    return (
      <p className="mt-2 text-xs text-muted-foreground">
        No status changes yet — incident is still in its original state.
      </p>
    );
  }

  return (
    <div className="mt-3 space-y-2 border-l border-border pl-3">
      {entries.map((entry: AuditEntry) => {
        const verb = ACTION_LABELS[entry.action] ?? entry.action;
        const actor = entry.actor_label || entry.actor_id || entry.actor_type;
        return (
          <div key={entry.id} className="flex items-start gap-2">
            <Clock className="mt-0.5 h-3 w-3 flex-shrink-0 text-muted-foreground" />
            <div className="flex-1 text-xs">
              <span className="text-foreground">{actor}</span>{" "}
              <span className="text-muted-foreground">{verb} this incident</span>
              <span className="ml-2 text-muted-foreground">
                · {new Date(entry.created_at).toLocaleString()}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
