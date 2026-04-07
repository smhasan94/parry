import { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from "recharts";
import { CHART_THEME } from "@/lib/chart-theme";
import type { AuditEntry } from "@/lib/types";

interface Props {
  entries: AuditEntry[];
}

interface Point {
  t: number;
  label: string;
  avg_tokens: number | null;
  avg_latency: number | null;
  event_count: number | null;
  reason: string;
  quality: string | null;
}

function extractBaseline(obj: unknown): {
  avg_tokens: number | null;
  avg_latency: number | null;
  event_count: number | null;
  quality: string | null;
} {
  if (!obj || typeof obj !== "object") {
    return { avg_tokens: null, avg_latency: null, event_count: null, quality: null };
  }
  const o = obj as Record<string, unknown>;
  return {
    avg_tokens: typeof o.avg_token_count === "number" ? o.avg_token_count : null,
    avg_latency: typeof o.avg_latency_ms === "number" ? o.avg_latency_ms : null,
    event_count: typeof o.event_count === "number" ? o.event_count : null,
    quality: typeof o.quality === "string" ? o.quality : null,
  };
}

/**
 * Reconstructs a baseline drift timeline from audit log `baseline.recomputed`
 * entries. Each recompute writes a `before`/`after` diff, so we walk entries
 * oldest→newest and emit one point per `after` snapshot, plus the very first
 * `before` (if non-null) as the origin point.
 *
 * Known limitation: the initial baseline autogen does NOT write an audit
 * entry (see detection_service.run_and_persist_detections). The origin of
 * the chart is therefore the baseline state *right before the first manual
 * or scheduled recompute*, which is the earliest snapshot we can reconstruct.
 */
export function BaselineDriftTimeline({ entries }: Props) {
  const data = useMemo<Point[]>(() => {
    // Sort ascending by timestamp — backend returns newest first
    const sorted = [...entries].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );

    const points: Point[] = [];

    // Seed with the `before` of the earliest entry so the chart has a
    // starting point rather than jumping straight to the first after-state.
    const first = sorted[0];
    if (first) {
      const details = (first.details ?? {}) as Record<string, unknown>;
      const before = extractBaseline(details.before);
      if (before.avg_tokens != null || before.avg_latency != null) {
        const t = new Date(first.created_at).getTime() - 1;
        points.push({
          t,
          label: "initial",
          avg_tokens: before.avg_tokens,
          avg_latency: before.avg_latency,
          event_count: before.event_count,
          reason: "initial",
          quality: before.quality,
        });
      }
    }

    for (const entry of sorted) {
      const details = (entry.details ?? {}) as Record<string, unknown>;
      const after = extractBaseline(details.after);
      points.push({
        t: new Date(entry.created_at).getTime(),
        label: new Date(entry.created_at).toLocaleDateString(),
        avg_tokens: after.avg_tokens,
        avg_latency: after.avg_latency,
        event_count: after.event_count,
        reason: typeof details.reason === "string" ? details.reason : "manual",
        quality: after.quality,
      });
    }

    return points;
  }, [entries]);

  if (data.length < 2) {
    return (
      <p className="text-sm text-muted-foreground">
        Not enough recomputes to plot drift. Baselines need at least two
        recorded recomputes before a timeline can be drawn.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div style={{ height: 180 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 5, right: 10, left: -10, bottom: 0 }}
          >
            <CartesianGrid stroke={CHART_THEME.grid} strokeDasharray="3 3" />
            <XAxis dataKey="label" stroke={CHART_THEME.text} fontSize={10} />
            <YAxis
              yAxisId="tokens"
              stroke="#3b82f6"
              fontSize={10}
              tickFormatter={(v) => `${Math.round(v)}t`}
            />
            <YAxis
              yAxisId="latency"
              orientation="right"
              stroke="#f97316"
              fontSize={10}
              tickFormatter={(v) => `${Math.round(v)}ms`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: CHART_THEME.tooltip.bg,
                border: `1px solid ${CHART_THEME.tooltip.border}`,
                color: CHART_THEME.tooltip.text,
                fontSize: 12,
              }}
              labelStyle={{ color: CHART_THEME.tooltip.text }}
              formatter={(value: number, name: string) => {
                if (name === "avg_tokens") return [Math.round(value), "avg tokens"];
                if (name === "avg_latency") return [`${Math.round(value)}ms`, "avg latency"];
                return [value, name];
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line
              yAxisId="tokens"
              type="monotone"
              dataKey="avg_tokens"
              stroke="#3b82f6"
              strokeWidth={1.5}
              dot={{ r: 3 }}
              name="avg tokens"
              isAnimationActive={false}
            />
            <Line
              yAxisId="latency"
              type="monotone"
              dataKey="avg_latency"
              stroke="#f97316"
              strokeWidth={1.5}
              dot={{ r: 3 }}
              name="avg latency"
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="max-h-40 space-y-1 overflow-y-auto text-xs">
        {data
          .slice()
          .reverse()
          .map((p, i) => (
            <div
              key={i}
              className="flex items-center justify-between border-b border-border py-1 last:border-0"
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-muted-foreground">{p.label}</span>
                <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                  {p.reason}
                </span>
                {p.quality && (
                  <span className="text-[10px] text-muted-foreground">
                    quality: {p.quality}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3 text-muted-foreground">
                {p.avg_tokens != null && <span>{Math.round(p.avg_tokens)}t</span>}
                {p.avg_latency != null && <span>{Math.round(p.avg_latency)}ms</span>}
                {p.event_count != null && <span>n={p.event_count}</span>}
              </div>
            </div>
          ))}
      </div>
    </div>
  );
}
