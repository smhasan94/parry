import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { RedTeamRunDetail } from "@/lib/api";

const GRADE_COLOR: Record<string, string> = {
  A: "text-emerald-400",
  B: "text-lime-400",
  C: "text-yellow-400",
  D: "text-orange-400",
  F: "text-red-400",
};

interface Props {
  run: RedTeamRunDetail;
}

/**
 * Hero card on the run detail page — big score, big grade,
 * total / detected counts, mode, timestamps.
 */
export function RedTeamScoreCard({ run }: Props) {
  const gradeClass = run.grade ? GRADE_COLOR[run.grade] : "text-muted-foreground";

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-6 p-6">
        <div className="flex flex-col items-center">
          <div className="text-5xl font-bold tabular-nums">
            {run.overall_score ?? "—"}
            {run.overall_score != null && (
              <span className="text-xl text-muted-foreground">/100</span>
            )}
          </div>
          <div className="text-xs uppercase text-muted-foreground">score</div>
        </div>
        <div className="flex flex-col items-center">
          <div className={`text-5xl font-bold ${gradeClass}`}>
            {run.grade ?? "—"}
          </div>
          <div className="text-xs uppercase text-muted-foreground">grade</div>
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <Badge variant="outline">{run.mode}</Badge>
            <Badge
              variant={
                run.status === "completed"
                  ? "secondary"
                  : run.status === "failed"
                    ? "destructive"
                    : "outline"
              }
            >
              {run.status}
            </Badge>
          </div>
          <div className="mt-2 text-sm text-muted-foreground">
            {run.detected_count ?? 0} / {run.total_attacks ?? 0} attacks caught
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            started {new Date(run.started_at).toLocaleString()}
            {run.completed_at && (
              <>
                {" · "}
                completed {new Date(run.completed_at).toLocaleString()}
              </>
            )}
          </div>
          {run.error_message && (
            <div className="mt-2 text-sm text-destructive">
              {run.error_message}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
