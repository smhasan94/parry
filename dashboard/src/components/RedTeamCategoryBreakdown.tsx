import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
  byCategory: Record<string, number>;
}

const CATEGORY_LABEL: Record<string, string> = {
  instruction_override: "Instruction override",
  jailbreak: "Jailbreak",
  data_exfil: "Data exfiltration",
  tool_hijack: "Tool hijack",
  privilege_escalation: "Privilege escalation",
  content_smuggling: "Content smuggling",
  indirect: "Indirect injection",
  cost_exploit: "Cost exploitation",
};

function colorFor(score: number): string {
  if (score >= 90) return "bg-emerald-500";
  if (score >= 75) return "bg-lime-500";
  if (score >= 60) return "bg-yellow-500";
  if (score >= 40) return "bg-orange-500";
  return "bg-red-500";
}

/**
 * Horizontal-bar breakdown of detection rate per attack category.
 * The customer spends most of their time looking at the bars that
 * aren't at 100%.
 */
export function RedTeamCategoryBreakdown({ byCategory }: Props) {
  const entries = Object.entries(byCategory).sort(([, a], [, b]) => a - b);
  if (entries.length === 0) {
    return null;
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Detection rate by category</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {entries.map(([category, score]) => (
            <li key={category} className="flex items-center gap-3 text-sm">
              <span className="w-44 truncate">
                {CATEGORY_LABEL[category] ?? category}
              </span>
              <div className="flex h-4 flex-1 overflow-hidden rounded bg-muted">
                <div
                  className={colorFor(score)}
                  style={{ width: `${score}%` }}
                />
              </div>
              <span className="w-10 text-right tabular-nums">{score}%</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
