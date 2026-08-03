import type { ShadowSystem } from "@/lib/types";

const RISK_LABELS: Record<string, string> = {
  unclassified: "Unclassified",
  minimal: "Minimal",
  limited: "Limited",
  high: "High",
  unacceptable: "Unacceptable",
};

const RISK_STYLES: Record<string, string> = {
  unclassified: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  minimal: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400",
  limited: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400",
  high: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400",
  unacceptable: "bg-red-600 text-white dark:bg-red-700",
};

function RiskBadge({ level }: { level: string }) {
  return (
    <span
      data-risk={level}
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
        RISK_STYLES[level] ?? RISK_STYLES.unclassified
      }`}
    >
      {RISK_LABELS[level] ?? level}
    </span>
  );
}

export function ShadowAITable({ systems }: { systems: ShadowSystem[] }) {
  if (systems.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-zinc-300 p-8 text-center dark:border-zinc-700">
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          No shadow AI found. Every discovered system is covered by an agent.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-zinc-200 text-xs uppercase text-zinc-500 dark:border-zinc-800">
          <tr>
            <th className="py-2 pr-4 font-medium">System</th>
            <th className="py-2 pr-4 font-medium">Vendor</th>
            <th className="py-2 pr-4 font-medium">Risk tier</th>
            <th className="py-2 pr-4 font-medium">Found via</th>
            <th className="py-2 font-medium">Last seen</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {systems.map((s) => (
            <tr key={s.id}>
              <td className="py-2 pr-4 font-medium text-zinc-900 dark:text-zinc-100">{s.name}</td>
              <td className="py-2 pr-4 text-zinc-600 dark:text-zinc-400">
                {s.provider_name ?? "—"}
              </td>
              <td className="py-2 pr-4">
                <RiskBadge level={s.risk_level} />
              </td>
              <td className="py-2 pr-4 text-zinc-600 dark:text-zinc-400">
                {s.discovery_source ?? "—"}
              </td>
              <td
                className="py-2 text-zinc-600 dark:text-zinc-400"
                title={s.last_seen_at ? `Last seen ${s.last_seen_at}` : "Never seen"}
              >
                {s.last_seen_at ? new Date(s.last_seen_at).toLocaleDateString() : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
