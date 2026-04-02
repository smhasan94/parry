import { useMemo } from "react";
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
import type { Incident } from "@/lib/types";

interface Props {
  incidents: Incident[];
}

export function DetectorBreakdown({ incidents }: Props) {
  const data = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const inc of incidents) {
      for (const det of inc.detections) {
        if (det.triggered) {
          counts[det.detector] = (counts[det.detector] || 0) + 1;
        }
      }
    }
    return Object.entries(counts)
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);
  }, [incidents]);

  if (data.length === 0) {
    return (
      <div className="flex h-[180px] items-center justify-center">
        <p className="text-sm text-muted-foreground">No detections for this agent</p>
      </div>
    );
  }

  return (
    <div className="h-[180px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 4, bottom: 0, left: 0 }}>
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
            dataKey="name"
            tick={{ fill: CHART_THEME.text, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={120}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: CHART_THEME.tooltip.bg,
              border: `1px solid ${CHART_THEME.tooltip.border}`,
              borderRadius: "0.375rem",
              color: CHART_THEME.tooltip.text,
              fontSize: "0.75rem",
            }}
            formatter={(value: number) => [value, "detections"]}
          />
          <Bar dataKey="count" fill="#f97316" radius={[0, 4, 4, 0]} barSize={18} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
