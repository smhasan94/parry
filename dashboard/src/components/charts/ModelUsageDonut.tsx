import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { CHART_THEME } from "@/lib/chart-theme";

interface Props {
  data: { model: string; count: number }[];
}

const PALETTE = [
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#f59e0b",
  "#10b981",
  "#06b6d4",
  "#ef4444",
  "#84cc16",
];

export function ModelUsageDonut({ data }: Props) {
  if (data.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center">
        <p className="text-sm text-muted-foreground">No model usage in this window</p>
      </div>
    );
  }
  return (
    <div className="h-[240px]">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="count"
            nameKey="model"
            innerRadius="55%"
            outerRadius="85%"
            paddingAngle={2}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={PALETTE[i % PALETTE.length]} stroke="none" />
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
          />
          <Legend
            verticalAlign="bottom"
            wrapperStyle={{ fontSize: "0.7rem", color: CHART_THEME.text }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
