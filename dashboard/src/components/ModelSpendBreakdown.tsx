interface Props {
  data: Array<{ model: string; count: number; spend_usd: number }>;
}

/**
 * Horizontal-bar breakdown of spend per model. Reused by both the
 * per-agent CostCard and the org-wide dashboard summary.
 */
export function ModelSpendBreakdown({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="text-xs text-muted-foreground italic">
        No model spend data yet.
      </div>
    );
  }
  const max = Math.max(...data.map((d) => d.spend_usd));
  return (
    <ul className="space-y-1">
      {data.map((d) => (
        <li key={d.model} className="flex items-center gap-2 text-xs">
          <span className="w-36 truncate font-mono">{d.model}</span>
          <div className="flex h-3 flex-1 overflow-hidden rounded bg-muted">
            <div
              className="bg-primary"
              style={{ width: `${max > 0 ? (d.spend_usd / max) * 100 : 0}%` }}
            />
          </div>
          <span className="w-20 text-right tabular-nums">
            ${d.spend_usd.toFixed(2)}
          </span>
          <span className="w-14 text-right tabular-nums text-muted-foreground">
            {d.count}
          </span>
        </li>
      ))}
    </ul>
  );
}
