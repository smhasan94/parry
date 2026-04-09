import { useParams, Link } from "@tanstack/react-router";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useRedTeamRun } from "@/hooks/useRedTeam";
import { RedTeamScoreCard } from "@/components/RedTeamScoreCard";
import { RedTeamCategoryBreakdown } from "@/components/RedTeamCategoryBreakdown";

const SEVERITY_CLASS: Record<string, string> = {
  critical: "text-red-400",
  high: "text-orange-400",
  medium: "text-yellow-400",
  low: "text-blue-400",
};

export function RedTeamRunDetailPage() {
  const { runId } = useParams({ from: "/red-team/$runId" });
  const { data: run, isLoading, error } = useRedTeamRun(runId);

  if (isLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading run…</div>
    );
  }
  if (error || !run) {
    return (
      <div className="p-6 text-sm text-destructive">
        Couldn't load run: {error?.message ?? "not found"}
      </div>
    );
  }

  return (
    <div>
      <Header title="Red Team Run" description={`Run ${run.id.slice(0, 8)}`} />
      <div className="px-6 pt-4">
        <Link to="/red-team" className="text-sm text-muted-foreground hover:underline">
          ← Back to runs
        </Link>
      </div>
      <div className="space-y-4 p-6">
        <RedTeamScoreCard run={run} />

        {run.by_category && (
          <RedTeamCategoryBreakdown byCategory={run.by_category} />
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Undetected attacks ({run.failures.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {run.failures.length === 0 ? (
              <div className="p-6 text-sm text-muted-foreground">
                ✓ Every attack in the corpus was caught.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-xs text-muted-foreground">
                    <th className="px-4 py-2 text-left font-medium">
                      Attack
                    </th>
                    <th className="px-4 py-2 text-left font-medium">
                      Category
                    </th>
                    <th className="px-4 py-2 text-left font-medium">
                      Severity
                    </th>
                    <th className="px-4 py-2 text-left font-medium">
                      Detectors that fired
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {run.failures.map((f) => (
                    <tr
                      key={f.attack_id}
                      className="border-b border-border last:border-0"
                    >
                      <td className="px-4 py-3 font-mono text-xs">
                        {f.attack_id}
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {f.category}
                      </td>
                      <td
                        className={`px-4 py-3 text-xs font-semibold ${
                          SEVERITY_CLASS[f.severity] ?? ""
                        }`}
                      >
                        {f.severity}
                      </td>
                      <td className="px-4 py-3">
                        {f.detectors_fired.length === 0 ? (
                          <span className="text-xs text-muted-foreground italic">
                            none
                          </span>
                        ) : (
                          f.detectors_fired.map((d) => (
                            <Badge
                              key={d}
                              variant="outline"
                              className="mr-1 text-xs"
                            >
                              {d}
                            </Badge>
                          ))
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
