import { LineChart, Line, ResponsiveContainer } from "recharts";

interface Props {
  data: number[];
  color?: string;
  height?: number;
}

export function Sparkline({ data, color = "#3b82f6", height = 32 }: Props) {
  if (data.length < 2) return null;

  const chartData = data.map((v, i) => ({ i, v }));

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData}>
          <Line
            type="monotone"
            dataKey="v"
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
