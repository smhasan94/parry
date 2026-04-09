import { useEffect, useRef, useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MatchSampleList } from "@/components/MatchSampleList";
import type { SimulationReport } from "@/lib/api";

interface Props {
  /** The async simulation runner — usually a `useMutation.mutateAsync`. */
  simulate: () => Promise<SimulationReport>;
  /** Trigger value: when this changes, the panel debounces + re-runs. */
  trigger: unknown;
  /** Hide the panel entirely (e.g. pattern is empty). */
  disabled?: boolean;
  /** Debounce window for `trigger` changes. */
  debounceMs?: number;
}

/**
 * Reusable preview panel for the policy regression runner.
 *
 * Used by both the custom rules editor and the policies editor.
 * Debounces re-runs so an admin typing a regex doesn't fire one
 * simulation per keystroke.
 */
export function RegressionPreviewPanel({
  simulate,
  trigger,
  disabled = false,
  debounceMs = 500,
}: Props) {
  const [report, setReport] = useState<SimulationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    if (disabled) {
      setReport(null);
      setError(null);
      return;
    }
    const myseq = ++seq.current;
    const handle = window.setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await simulate();
        // Drop stale results if a newer trigger superseded us.
        if (myseq !== seq.current) return;
        setReport(result);
      } catch (e) {
        if (myseq !== seq.current) return;
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (myseq === seq.current) setLoading(false);
      }
    }, debounceMs);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger, disabled]);

  if (disabled) return null;

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle className="text-base">Regression preview</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && (
          <div className="text-sm text-muted-foreground">
            Running against your recent events…
          </div>
        )}
        {error && (
          <div className="text-sm text-destructive">{error}</div>
        )}
        {report && !loading && <ReportBody report={report} />}
        {!report && !loading && !error && (
          <div className="text-sm text-muted-foreground">
            Edit the rule to see how it would have matched recent events.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ReportBody({ report }: { report: SimulationReport }) {
  if (!report.pattern_is_valid) {
    return (
      <div className="text-sm text-destructive">
        ⚠ {report.error || "Invalid pattern."}
      </div>
    );
  }

  const matchPct = (report.match_rate * 100).toFixed(2);
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="default">✓ valid</Badge>
        <span>
          <strong>{report.matched_count.toLocaleString()}</strong> matches in{" "}
          {report.days_checked} days
        </span>
        <span className="text-muted-foreground">
          ({matchPct}% of {report.total_events_checked.toLocaleString()} events
          checked)
        </span>
        {report.truncated && (
          <Badge variant="outline" className="text-amber-600">
            partial — event cap hit
          </Badge>
        )}
      </div>

      {Object.keys(report.by_agent).length > 0 && (
        <div>
          <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            By agent
          </div>
          <ByAgentBars data={report.by_agent} />
        </div>
      )}

      {Object.keys(report.by_day).length > 0 && (
        <div>
          <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            By day
          </div>
          <BydaySparkline data={report.by_day} days={report.days_checked} />
        </div>
      )}

      <div>
        <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
          Sample matches
        </div>
        <MatchSampleList samples={report.samples} />
      </div>
    </>
  );
}

function ByAgentBars({ data }: { data: Record<string, number> }) {
  const sorted = Object.entries(data).sort(([, a], [, b]) => b - a);
  const top = sorted.slice(0, 6);
  const rest = sorted.slice(6);
  if (rest.length > 0) {
    const otherTotal = rest.reduce((acc, [, v]) => acc + v, 0);
    top.push([`+${rest.length} others`, otherTotal]);
  }
  const max = Math.max(...top.map(([, v]) => v));
  return (
    <ul className="space-y-1">
      {top.map(([name, count]) => (
        <li key={name} className="flex items-center gap-2 text-xs">
          <span className="w-32 truncate">{name}</span>
          <div className="flex h-3 flex-1 overflow-hidden rounded bg-muted">
            <div
              className="bg-primary"
              style={{ width: `${(count / max) * 100}%` }}
            />
          </div>
          <span className="w-10 text-right tabular-nums">{count}</span>
        </li>
      ))}
    </ul>
  );
}

function BydaySparkline({
  data,
  days,
}: {
  data: Record<string, number>;
  days: number;
}) {
  const today = new Date();
  const series: { day: string; count: number }[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    series.push({ day: key, count: data[key] ?? 0 });
  }
  const max = Math.max(1, ...series.map((s) => s.count));
  return (
    <div className="flex h-12 items-end gap-px">
      {series.map((s) => (
        <div
          key={s.day}
          title={`${s.day}: ${s.count}`}
          className="flex-1 bg-primary/70"
          style={{ height: `${Math.max(2, (s.count / max) * 100)}%` }}
        />
      ))}
    </div>
  );
}
