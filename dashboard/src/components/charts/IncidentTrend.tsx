import { useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { SEVERITY_COLORS, SEVERITY_ORDER, CHART_THEME } from "@/lib/chart-theme";
import type { Incident } from "@/lib/types";

interface Props {
  incidents: Incident[];
}

function formatDay(date: Date): string {
  return date.toLocaleDateString("en-US", { weekday: "short" });
}

function dateKey(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function IncidentTrend({ incidents }: Props) {
  const data = useMemo(() => {
    // Build last 7 days
    const days: { date: Date; key: string; label: string }[] = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      d.setHours(0, 0, 0, 0);
      days.push({ date: d, key: dateKey(d), label: formatDay(d) });
    }

    // Count incidents per day per severity
    const counts: Record<string, Record<string, number>> = {};
    for (const day of days) {
      counts[day.key] = { critical: 0, high: 0, medium: 0, low: 0 };
    }
    for (const inc of incidents) {
      const key = dateKey(new Date(inc.created_at));
      if (counts[key]) {
        counts[key][inc.severity] = (counts[key][inc.severity] || 0) + 1;
      }
    }

    return days.map((day) => ({
      name: day.label,
      ...counts[day.key],
    }));
  }, [incidents]);

  const hasData = incidents.length > 0;

  if (!hasData) {
    return (
      <div className="flex h-[200px] items-center justify-center">
        <p className="text-sm text-muted-foreground">No incidents in the last 7 days</p>
      </div>
    );
  }

  return (
    <div className="h-[200px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_THEME.grid} vertical={false} />
          <XAxis
            dataKey="name"
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
          {[...SEVERITY_ORDER].reverse().map((severity) => (
            <Area
              key={severity}
              type="monotone"
              dataKey={severity}
              stackId="1"
              fill={SEVERITY_COLORS[severity]}
              stroke={SEVERITY_COLORS[severity]}
              fillOpacity={0.6}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
