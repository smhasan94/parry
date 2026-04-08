import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { CHART_THEME } from "@/lib/chart-theme";

interface Props {
  data: { tool: string; count: number }[];
}

/**
 * Horizontal bar chart of the top tools an agent has called.
 * "Heatmap" in name only — the plan calls it that but a ranked bar
 * chart communicates the signal far better at this density.
 */
export function ToolCallHeatmap({ data }: Props) {
  if (data.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center">
        <p className="text-sm text-muted-foreground">
          No tool calls recorded in this window
        </p>
      </div>
    );
  }
  const height = Math.max(200, data.length * 28);
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 12, bottom: 0, left: 4 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_THEME.grid} horizontal={false} />
          <XAxis
            type="number"
            tick={{ fill: CHART_THEME.text, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="tool"
            width={120}
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
          />
          <Bar dataKey="count" fill="#6366f1" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
