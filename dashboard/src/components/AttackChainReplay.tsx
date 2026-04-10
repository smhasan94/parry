import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/ui/states";
import {
  Play,
  AlertTriangle,
  Shield,
  Radio,
  ChevronDown,
  ChevronUp,
  Crosshair,
  Wrench,
} from "lucide-react";
import type { ReplayEvent } from "@/lib/types";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "border-red-500 bg-red-50",
  high: "border-orange-400 bg-orange-50",
  medium: "border-yellow-400 bg-yellow-50",
  low: "border-gray-300 bg-gray-50",
};

function ReplayEventCard({ event }: { event: ReplayEvent }) {
  const [expanded, setExpanded] = useState(false);
  const hasAnnotations =
    event.annotations.detections.length > 0 ||
    event.annotations.permission_violations.length > 0 ||
    event.annotations.threat_intel_matches.length > 0;

  const borderClass = event.is_trigger
    ? "border-l-4 border-l-red-500 bg-red-50/50"
    : hasAnnotations
      ? "border-l-4 border-l-yellow-400"
      : "border-l-2 border-l-gray-200";

  return (
    <div className={`rounded-md border p-3 text-xs ${borderClass}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {event.is_trigger && (
            <span className="flex items-center gap-1 rounded bg-red-100 px-1.5 py-0.5 text-xs font-bold text-red-700">
              <Crosshair className="h-3 w-3" />
              TRIGGER
            </span>
          )}
          <span className="text-muted-foreground">
            {event.timestamp
              ? new Date(event.timestamp).toLocaleTimeString()
              : "—"}
          </span>
          {event.model && (
            <span className="font-mono text-muted-foreground">{event.model}</span>
          )}
          {event.token_count && (
            <span className="text-muted-foreground">
              {event.token_count.toLocaleString()} tokens
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {/* Annotation badges */}
          {event.annotations.detections.length > 0 && (
            <span className="flex items-center gap-0.5 rounded bg-red-100 px-1.5 py-0.5 text-red-700">
              <AlertTriangle className="h-3 w-3" />
              {event.annotations.detections.length}
            </span>
          )}
          {event.annotations.permission_violations.length > 0 && (
            <span className="flex items-center gap-0.5 rounded bg-orange-100 px-1.5 py-0.5 text-orange-700">
              <Shield className="h-3 w-3" />
              {event.annotations.permission_violations.length}
            </span>
          )}
          {event.annotations.threat_intel_matches.length > 0 && (
            <span className="flex items-center gap-0.5 rounded bg-purple-100 px-1.5 py-0.5 text-purple-700">
              <Radio className="h-3 w-3" />
              TI
            </span>
          )}
          {event.tool_calls && event.tool_calls.length > 0 && (
            <span className="flex items-center gap-0.5 rounded bg-blue-100 px-1.5 py-0.5 text-blue-700">
              <Wrench className="h-3 w-3" />
              {event.tool_calls.length}
            </span>
          )}
          <button onClick={() => setExpanded(!expanded)} className="ml-1">
            {expanded ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
        </div>
      </div>

      {/* Tool calls summary */}
      {event.tool_calls && event.tool_calls.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {event.tool_calls.map((tc, i) => {
            const name =
              (tc as Record<string, unknown>).name ||
              ((tc as Record<string, unknown>).function as Record<string, unknown>)
                ?.name ||
              "unknown";
            return (
              <span
                key={i}
                className="rounded bg-blue-50 px-1.5 py-0.5 font-mono text-blue-700"
              >
                {String(name)}
              </span>
            );
          })}
        </div>
      )}

      {/* Expanded content */}
      {expanded && (
        <div className="mt-3 space-y-2">
          {/* Prompt/Response previews */}
          {event.prompt_preview && (
            <div>
              <p className="font-medium text-muted-foreground">Prompt:</p>
              <p className="mt-0.5 whitespace-pre-wrap rounded bg-muted/50 p-2 font-mono">
                {event.prompt || event.prompt_preview}
              </p>
            </div>
          )}
          {event.response_preview && (
            <div>
              <p className="font-medium text-muted-foreground">Response:</p>
              <p className="mt-0.5 whitespace-pre-wrap rounded bg-muted/50 p-2 font-mono">
                {event.response || event.response_preview}
              </p>
            </div>
          )}

          {/* Detection details */}
          {event.annotations.detections.length > 0 && (
            <div>
              <p className="font-medium text-red-700">Detections:</p>
              {event.annotations.detections.map((d, i) => (
                <div
                  key={i}
                  className="mt-1 rounded border border-red-200 bg-red-50 p-2"
                >
                  <span className="font-medium">{d.detector}</span>
                  <span
                    className={`ml-2 rounded px-1 py-0.5 text-[10px] font-medium ${
                      SEVERITY_COLORS[d.severity]
                        ? "text-red-800"
                        : "text-gray-800"
                    }`}
                  >
                    {d.severity}
                  </span>
                  <span className="ml-2 text-muted-foreground">
                    {(d.confidence * 100).toFixed(0)}%
                  </span>
                  <p className="mt-1 text-muted-foreground">{d.reason}</p>
                </div>
              ))}
            </div>
          )}

          {/* Permission violations */}
          {event.annotations.permission_violations.length > 0 && (
            <div>
              <p className="font-medium text-orange-700">Permission Violations:</p>
              {event.annotations.permission_violations.map((v, i) => (
                <p key={i} className="mt-1 text-orange-700">
                  {v}
                </p>
              ))}
            </div>
          )}

          {/* Threat intel */}
          {event.annotations.threat_intel_matches.length > 0 && (
            <div>
              <p className="font-medium text-purple-700">Threat Intel Matches:</p>
              <p className="mt-1 text-purple-600">
                Pattern matches {event.annotations.threat_intel_matches.length}{" "}
                indicator(s) from the cross-org threat feed
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function AttackChainReplay({ incidentId }: { incidentId: string }) {
  const [open, setOpen] = useState(false);
  const { data: replay, isLoading, isError } = useQuery({
    queryKey: ["incident-replay", incidentId],
    queryFn: () => api.getIncidentReplay(incidentId),
    enabled: open,
  });

  if (!open) {
    return (
      <Button
        size="sm"
        variant="ghost"
        onClick={() => setOpen(true)}
        title="Replay attack chain"
      >
        <Play className="h-4 w-4" />
      </Button>
    );
  }

  return (
    <Card className="mt-3">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Play className="h-4 w-4" />
          Attack Chain Replay
        </CardTitle>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {replay && (
            <>
              <span>
                Showing {replay.window_size} of {replay.total_session_events} events
              </span>
              <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
                Close
              </Button>
            </>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <LoadingState label="Reconstructing attack chain..." />
        ) : isError ? (
          <p className="text-sm text-destructive">
            Failed to load replay. This incident may not have session data.
          </p>
        ) : replay ? (
          <div className="space-y-2">
            {replay.events.map((event) => (
              <ReplayEventCard key={event.id} event={event} />
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
