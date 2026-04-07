import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
  Cell,
} from "recharts";
import { api, type AnomalyDriftHistogram, type DriftSeries } from "@/lib/api";
import { CHART_THEME } from "@/lib/chart-theme";

/** Convert cumulative bucket counts to per-bucket counts and flatten
 * across all series matching the filter predicate. */
function toBarData(
  series: DriftSeries[],
  keep: (s: DriftSeries) => boolean,
): { label: string; upper: number; count: number }[] {
  // Pick the first matching series' bucket shape as the canonical x axis.
  const sample = series.find(keep);
  if (!sample) return [];

  // bucket.le is cumulative upper bound; null = +Inf
  const boundaries = sample.buckets.map((b) => b.le);
  const bars: { label: string; upper: number; count: number }[] = [];
  let prevUpper = 0;

  for (let i = 0; i < boundaries.length; i++) {
    const le = boundaries[i] ?? null;
    let bucketCount = 0;
    for (const s of series) {
      if (!keep(s)) continue;
      const here = s.buckets[i]?.count ?? 0;
      const previous = i > 0 ? (s.buckets[i - 1]?.count ?? 0) : 0;
      bucketCount += here - previous;
    }
    const upper = le ?? prevUpper + 1;
    const label =
      le === null ? `>${prevUpper.toFixed(1)}` : `≤${le.toFixed(1)}`;
    bars.push({ label, upper, count: bucketCount });
    prevUpper = le ?? prevUpper;
  }

  return bars;
}

export function useAnomalyDriftHistogram() {
  return useQuery<AnomalyDriftHistogram>({
    queryKey: ["metrics", "anomaly-drift"],
    queryFn: () => api.getAnomalyDriftHistogram(),
    refetchInterval: 30_000,
  });
}

interface Props {
  /** Current sigma threshold from detector config — drawn as a vertical
   * reference line so users can see where their tuning knob sits. */
  currentSigma?: number;
}

export function DriftHistogram({ currentSigma }: Props) {
  const { data, isLoading, error } = useAnomalyDriftHistogram();

  const bars = useMemo(() => {
    if (!data) return [];
    // Aggregate across quality tiers — the user is tuning one threshold
    // and the chart should reflect all traffic the detector saw.
    return toBarData(data.series, () => true);
  }, [data]);

  const totalObservations = bars.reduce((sum, b) => sum + b.count, 0);

  if (isLoading) {
    return <p className="text-xs text-muted-foreground">Loading drift data…</p>;
  }
  if (error) {
    return (
      <p className="text-xs text-muted-foreground">
        Drift histogram unavailable.
      </p>
    );
  }
  if (totalObservations === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No drift observations recorded yet. The chart populates once the
        anomaly detector runs against live traffic.
      </p>
    );
  }

  // Color bars that would fire at the current threshold
  const fireColor = "#ef4444";
  const quietColor = "#3b82f6";

  return (
    <div className="space-y-2">
      <div style={{ height: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={bars}
            margin={{ top: 5, right: 10, left: -20, bottom: 0 }}
          >
            <CartesianGrid stroke={CHART_THEME.grid} strokeDasharray="3 3" />
            <XAxis dataKey="label" stroke={CHART_THEME.text} fontSize={10} />
            <YAxis stroke={CHART_THEME.text} fontSize={10} allowDecimals={false} />
            <Tooltip
              contentStyle={{
                backgroundColor: CHART_THEME.tooltip.bg,
                border: `1px solid ${CHART_THEME.tooltip.border}`,
                color: CHART_THEME.tooltip.text,
                fontSize: 12,
              }}
              labelStyle={{ color: CHART_THEME.tooltip.text }}
              formatter={(value: number) => [`${value} events`, "count"]}
            />
            {currentSigma != null && (
              <ReferenceLine
                x={
                  bars.find((b) => b.upper >= currentSigma)?.label ??
                  bars[bars.length - 1]?.label
                }
                stroke={fireColor}
                strokeDasharray="2 2"
                label={{
                  value: `σ = ${currentSigma.toFixed(1)}`,
                  fill: fireColor,
                  fontSize: 10,
                  position: "top",
                }}
              />
            )}
            <Bar dataKey="count" isAnimationActive={false}>
              {bars.map((b) => (
                <Cell
                  key={b.label}
                  fill={currentSigma != null && b.upper >= currentSigma ? fireColor : quietColor}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10px] text-muted-foreground">
        {totalObservations} observations across all baseline qualities. Red
        bars would trigger at the current σ threshold.
      </p>
    </div>
  );
}
