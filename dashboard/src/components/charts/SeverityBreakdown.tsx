import { useMemo } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { SEVERITY_COLORS, SEVERITY_ORDER, CHART_THEME } from "@/lib/chart-theme";
import type { Incident } from "@/lib/types";

interface Props {
  incidents: Incident[];
}

export function SeverityBreakdown({ incidents }: Props) {
  const data = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const i of incidents) {
      counts[i.severity] = (counts[i.severity] || 0) + 1;
    }
    return SEVERITY_ORDER
      .map((s) => ({ name: s, value: counts[s] || 0 }))
      .filter((d) => d.value > 0);
  }, [incidents]);

  if (data.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center">
        <p className="text-sm text-muted-foreground">No incidents yet</p>
      </div>
    );
  }

  return (
    <div className="h-[200px]">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={50}
            outerRadius={80}
            dataKey="value"
            stroke="none"
          >
            {data.map((entry) => (
              <Cell
                key={entry.name}
                fill={SEVERITY_COLORS[entry.name as keyof typeof SEVERITY_COLORS]}
              />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              backgroundColor: CHART_THEME.tooltip.bg,
              border: `1px solid ${CHART_THEME.tooltip.border}`,
              borderRadius: "0.375rem",
              color: CHART_THEME.tooltip.text,
              fontSize: "0.75rem",
            }}
            formatter={(value: number, name: string) => [value, name]}
          />
          <text
            x="50%"
            y="50%"
            textAnchor="middle"
            dominantBaseline="central"
            className="fill-foreground text-2xl font-bold"
          >
            {incidents.length}
          </text>
        </PieChart>
      </ResponsiveContainer>
      <div className="flex justify-center gap-3">
        {data.map((entry) => (
          <div key={entry.name} className="flex items-center gap-1.5 text-xs">
            <div
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: SEVERITY_COLORS[entry.name as keyof typeof SEVERITY_COLORS] }}
            />
            <span className="capitalize text-muted-foreground">
              {entry.name} ({entry.value})
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
