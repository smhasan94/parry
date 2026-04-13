import { useMemo, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useSession, useSessionIncidents } from "@/hooks/useSession";
import type { SessionReplayEvent, SessionDetection } from "@/lib/api";
import type { Incident } from "@/lib/types";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  ExternalLink,
  Radio,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Vertical timeline view of every event in a session, oldest first.
 *
 * Cards with a triggered detection get a coloured left border
 * (critical/high = red, medium = orange, low = zinc) so analysts can
 * scan a 200-event session and spot the hot spots immediately. The
 * page polls every 5 seconds while the session is still open (see
 * useSession) so live sessions animate in without a manual refresh.
 */

const SEV_BORDER: Record<string, string> = {
  critical: "border-l-red-500",
  high: "border-l-red-500",
  medium: "border-l-orange-500",
  low: "border-l-zinc-500",
};

const SEV_TEXT: Record<string, string> = {
  critical: "text-red-300",
  high: "text-red-300",
  medium: "text-orange-300",
  low: "text-zinc-300",
};

function highestTriggeredSeverity(
  detections: SessionDetection[],
): string | null {
  const order = ["critical", "high", "medium", "low"];
  for (const sev of order) {
    if (detections.some((d) => d.triggered && d.severity === sev)) return sev;
  }
  return null;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rest = s % 60;
  return `${m}m ${rest}s`;
}

function formatRelative(startIso: string | null, eventIso: string | null): string {
  if (!startIso || !eventIso) return "";
  const start = new Date(startIso).getTime();
  const at = new Date(eventIso).getTime();
  const delta = Math.max(0, at - start);
  return `+${formatDuration(delta)}`;
}

const SEV_BANNER_BG: Record<string, string> = {
  critical: "bg-red-950/40 border-red-700/50",
  high: "bg-red-950/30 border-red-700/40",
  medium: "bg-orange-950/30 border-orange-700/40",
  low: "bg-zinc-800/40 border-zinc-600/40",
};

const SEV_BADGE: Record<string, string> = {
  critical: "bg-red-900/60 text-red-300 border-red-700/60",
  high: "bg-red-900/50 text-red-300 border-red-700/50",
  medium: "bg-orange-900/50 text-orange-300 border-orange-700/50",
  low: "bg-zinc-800/60 text-zinc-300 border-zinc-600/60",
};

function IncidentBanner({ incidents }: { incidents: Incident[] }) {
  if (incidents.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <AlertTriangle className="h-3.5 w-3.5" />
        <span>Incidents triggered by this session</span>
      </div>
      <ul className="space-y-2">
        {incidents.map((incident) => (
          <li
            key={incident.id}
            className={cn(
              "flex items-center justify-between gap-4 rounded-md border px-4 py-3",
              SEV_BANNER_BG[incident.severity] ?? "bg-muted/20 border-border",
            )}
          >
            <div className="flex min-w-0 items-center gap-3">
              <span
                className={cn(
                  "shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                  SEV_BADGE[incident.severity] ?? "bg-muted/30 text-muted-foreground border-border",
                )}
              >
                {incident.severity}
              </span>
              <span className="truncate text-sm font-medium text-foreground">
                {incident.title}
              </span>
              <span
                className={cn(
                  "shrink-0 rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                  "bg-muted/30 text-muted-foreground border-border",
                )}
              >
                {incident.status}
              </span>
            </div>
            <Link to="/incidents">
              <Button variant="ghost" size="sm" className="shrink-0 gap-1 text-xs">
                View Incident
                <ExternalLink className="h-3 w-3" />
              </Button>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function EventCard({
  event,
  startedAt,
  index,
}: {
  event: SessionReplayEvent;
  startedAt: string | null;
  index: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const topSeverity = highestTriggeredSeverity(event.detections);
  const border = topSeverity ? SEV_BORDER[topSeverity] : "border-l-transparent";
  const fullPrompt = event.prompt ?? null;
  const fullResponse = event.response ?? null;
  const canShowFull = fullPrompt !== null || fullResponse !== null;

  return (
    <li
      className={cn(
        "rounded-md border border-border border-l-4 bg-muted/10 p-4",
        border,
      )}
    >
      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <div className="flex items-center gap-3">
          <span className="font-mono">#{index + 1}</span>
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {formatRelative(startedAt, event.timestamp)}
          </span>
          {event.model && (
            <span className="flex items-center gap-1">
              <Cpu className="h-3 w-3" />
              {event.model}
            </span>
          )}
          {event.latency_ms !== null && (
            <span className="flex items-center gap-1">
              <Zap className="h-3 w-3" />
              {formatDuration(event.latency_ms)}
            </span>
          )}
          {event.token_count !== null && <span>{event.token_count} tok</span>}
        </div>
        <div className="flex items-center gap-2">
          {event.detections
            .filter((d) => d.triggered)
            .map((d) => (
              <span
                key={d.id}
                className={cn(
                  "rounded border border-border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                  SEV_TEXT[d.severity] ?? "text-muted-foreground",
                )}
                title={d.reason}
              >
                {d.detector}
              </span>
            ))}
        </div>
      </div>

      <div className="mt-3 space-y-2 text-sm">
        {event.prompt_preview && (
          <div>
            <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Prompt
            </p>
            <p className="whitespace-pre-wrap text-foreground/90">
              {expanded && fullPrompt ? fullPrompt : event.prompt_preview}
            </p>
          </div>
        )}
        {event.response_preview && (
          <div>
            <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Response
            </p>
            <p className="whitespace-pre-wrap text-foreground/80">
              {expanded && fullResponse ? fullResponse : event.response_preview}
            </p>
          </div>
        )}
        {event.tool_calls.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {event.tool_calls.map((call, i) => {
              const name =
                (call as { name?: string; tool?: string }).name ??
                (call as { tool?: string }).tool ??
                "tool";
              return (
                <span
                  key={i}
                  className="rounded-full border border-border bg-muted/30 px-2 py-0.5 text-[10px]"
                >
                  {name}
                </span>
              );
            })}
          </div>
        )}
      </div>

      {canShowFull && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          {expanded ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
          {expanded ? "Collapse" : "Show full"}
        </button>
      )}
    </li>
  );
}

export function SessionReplayPage() {
  const { sessionId } = useParams({ from: "/sessions/$sessionId" });
  const { data, isLoading, error } = useSession(sessionId);
  const { data: incidentsData } = useSessionIncidents(sessionId);

  const duration = useMemo(() => {
    if (!data) return null;
    const start = data.session.started_at
      ? new Date(data.session.started_at).getTime()
      : null;
    const end = data.session.ended_at
      ? new Date(data.session.ended_at).getTime()
      : Date.now();
    if (start === null) return null;
    return formatDuration(Math.max(0, end - start));
  }, [data]);

  if (isLoading) {
    return (
      <div>
        <Header title="Session Replay" />
        <div className="p-6">
          <p className="text-sm text-muted-foreground">Loading session…</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div>
        <Header title="Session Not Found" />
        <div className="p-6">
          <p className="text-sm text-muted-foreground">
            This session doesn't exist or belongs to another organization.
          </p>
          <Link to="/agents">
            <Button variant="ghost" size="sm" className="mt-3">
              <ArrowLeft className="h-4 w-4" />
              Back to agents
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  const isLive = data.session.ended_at === null;

  return (
    <div>
      <Header
        title="Session Replay"
        description={`Agent: ${data.session.agent_name}`}
        actions={
          <Link
            to="/agents/$agentId"
            params={{ agentId: data.session.agent_id }}
          >
            <Button variant="ghost" size="sm">
              <ArrowLeft className="h-4 w-4" />
              Back to Agent
            </Button>
          </Link>
        }
      />

      <div className="space-y-6 p-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center justify-between text-base">
              <span>Session Summary</span>
              {isLive && (
                <span className="flex items-center gap-2 text-xs text-green-400">
                  <Radio className="h-3 w-3 animate-pulse" />
                  LIVE
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
              <div>
                <dt className="text-xs uppercase text-muted-foreground">Events</dt>
                <dd className="text-lg font-semibold">
                  {data.session.event_count}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-muted-foreground">Duration</dt>
                <dd className="text-lg font-semibold">{duration ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-muted-foreground">
                  Triggered
                </dt>
                <dd
                  className={cn(
                    "text-lg font-semibold",
                    data.session.triggered_detection_count > 0
                      ? "text-red-300"
                      : "text-foreground",
                  )}
                >
                  {data.session.triggered_detection_count}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-muted-foreground">Started</dt>
                <dd className="text-sm">
                  {data.session.started_at
                    ? new Date(data.session.started_at).toLocaleString()
                    : "—"}
                </dd>
              </div>
            </dl>
          </CardContent>
        </Card>

        {incidentsData && incidentsData.incidents.length > 0 && (
          <IncidentBanner incidents={incidentsData.incidents} />
        )}

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Event Timeline</CardTitle>
          </CardHeader>
          <CardContent>
            {data.events.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-8 text-center">
                <Clock className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm font-medium">
                  {isLive ? "Session is live — waiting for first event" : "Session has no events"}
                </p>
                <p className="max-w-sm text-xs text-muted-foreground">
                  {isLive
                    ? "This page polls every 5 seconds. The next event from the SDK will appear here automatically."
                    : "The session was opened but no LLM calls were recorded before it ended."}
                </p>
              </div>
            ) : (
              <ol className="space-y-3">
                {data.events.map((e, i) => (
                  <EventCard
                    key={e.id}
                    event={e}
                    startedAt={data.session.started_at}
                    index={i}
                  />
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
