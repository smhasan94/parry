import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
  Dot,
} from "recharts";
import { CHART_THEME } from "@/lib/chart-theme";

interface Props {
  data: { date: string; avg_score: number }[];
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// Highlight points above the trigger threshold in red so eyes land
// on actual spikes even at a glance.
interface ScorePoint {
  avg_score?: number;
}

function ScoreDot(props: { cx?: number; cy?: number; payload?: ScorePoint }) {
  const { cx, cy, payload } = props;
  if (cx === undefined || cy === undefined) return null;
  const score = payload?.avg_score ?? 0;
  const color = score > 0.7 ? "#ef4444" : score > 0.5 ? "#f59e0b" : "#8b5cf6";
  return <Dot cx={cx} cy={cy} r={3} fill={color} stroke="none" />;
}

export function AnomalyTrend({ data }: Props) {
  if (data.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center">
        <p className="text-sm text-muted-foreground">
          No anomaly signal in this window
        </p>
      </div>
    );
  }
  const formatted = data.map((d) => ({ ...d, label: formatDay(d.date) }));
  return (
    <div className="h-[200px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={formatted} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_THEME.grid} vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: CHART_THEME.text, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={[0, 1]}
            tick={{ fill: CHART_THEME.text, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: CHART_THEME.tooltip.bg,
              border: `1px solid ${CHART_THEME.tooltip.border}`,
              borderRadius: "0.375rem",
              color: CHART_THEME.tooltip.text,
              fontSize: "0.75rem",
            }}
            formatter={(v: number) => v.toFixed(3)}
          />
          <ReferenceLine
            y={0.5}
            stroke="#f59e0b"
            strokeDasharray="4 4"
            label={{
              value: "ambiguous",
              fill: "#f59e0b",
              fontSize: 9,
              position: "right",
            }}
          />
          <ReferenceLine
            y={0.7}
            stroke="#ef4444"
            strokeDasharray="4 4"
            label={{
              value: "triggered",
              fill: "#ef4444",
              fontSize: 9,
              position: "right",
            }}
          />
          <Line
            type="monotone"
            dataKey="avg_score"
            stroke="#8b5cf6"
            strokeWidth={2}
            dot={<ScoreDot />}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
