import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { CHART_THEME } from "@/lib/chart-theme";

interface Props {
  data: { date: string; count: number }[];
  color?: string;
}

function formatDay(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function EventVolume({ data, color = "#3b82f6" }: Props) {
  if (data.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center">
        <p className="text-sm text-muted-foreground">No events in this window</p>
      </div>
    );
  }
  const formatted = data.map((d) => ({ ...d, label: formatDay(d.date) }));
  return (
    <div className="h-[200px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={formatted} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_THEME.grid} vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: CHART_THEME.text, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: CHART_THEME.text, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
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
          <Area
            type="monotone"
            dataKey="count"
            fill={color}
            stroke={color}
            fillOpacity={0.35}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
