import {
  LineChart,
  Line,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceArea,
  YAxis,
} from "recharts";

interface Props {
  data: number[];
  color?: string;
  height?: number;
  baselineMean?: number;
  baselineStd?: number;
}

export function Sparkline({
  data,
  color = "#3b82f6",
  height = 32,
  baselineMean,
  baselineStd,
}: Props) {
  if (data.length < 2) return null;

  const chartData = data.map((v, i) => ({ i, v }));
  const showBaseline = baselineMean != null && baselineMean > 0;
  const bandLow = showBaseline ? baselineMean - (baselineStd ?? 0) : undefined;
  const bandHigh = showBaseline ? baselineMean + (baselineStd ?? 0) : undefined;

  // Compute y-domain to include both data and baseline band
  const allValues = [...data];
  if (showBaseline) {
    allValues.push(baselineMean);
    if (bandLow != null) allValues.push(bandLow);
    if (bandHigh != null) allValues.push(bandHigh);
  }
  const yMin = Math.min(...allValues);
  const yMax = Math.max(...allValues);

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData}>
          <YAxis hide domain={[yMin, yMax]} />
          {showBaseline && bandLow != null && bandHigh != null && bandHigh > bandLow && (
            <ReferenceArea
              y1={bandLow}
              y2={bandHigh}
              fill={color}
              fillOpacity={0.08}
              strokeOpacity={0}
            />
          )}
          {showBaseline && (
            <ReferenceLine
              y={baselineMean}
              stroke={color}
              strokeDasharray="2 2"
              strokeOpacity={0.5}
            />
          )}
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
