import { useState } from "react";
import { Header } from "@/components/Header";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Link } from "@tanstack/react-router";
import {
  useRedTeamCorpus,
  useRedTeamRuns,
  useStartRedTeamRun,
} from "@/hooks/useRedTeam";
import { useAgents } from "@/hooks/useAgents";
import { useRole } from "@/hooks/useRole";
import { Shield, Play } from "lucide-react";

const GRADE_COLOR: Record<string, string> = {
  A: "text-emerald-400",
  B: "text-lime-400",
  C: "text-yellow-400",
  D: "text-orange-400",
  F: "text-red-400",
};

export function RedTeamPage() {
  const { data: runs = [], isLoading } = useRedTeamRuns();
  const { data: agents = [] } = useAgents();
  const { data: corpus } = useRedTeamCorpus();
  const startRun = useStartRedTeamRun();
  const { can } = useRole();
  const canMutate = can("admin");

  const [showStart, setShowStart] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<string>("");

  const agentName = (id: string) =>
    agents.find((a) => a.id === id)?.name ?? id.slice(0, 8);

  return (
    <div>
      <Header
        title="Red Team"
        description="Replay a curated attack corpus against an agent's detection stack"
        actions={
          canMutate ? (
            <Button size="sm" onClick={() => setShowStart((v) => !v)}>
              <Play className="h-4 w-4" />
              Start a run
            </Button>
          ) : undefined
        }
      />

      <div className="space-y-4 p-6">
        {corpus && (
          <Card>
            <CardContent className="flex flex-wrap items-center gap-3 py-3 text-sm text-muted-foreground">
              <Shield className="h-4 w-4" />
              <span>
                Bundled corpus: <strong>{corpus.total_attacks}</strong> attacks
                across {Object.keys(corpus.by_category).length} categories
              </span>
            </CardContent>
          </Card>
        )}

        {showStart && canMutate && (
          <Card>
            <CardHeader>
              <CardTitle>Start a sandbox run</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Agent</label>
                <select
                  value={selectedAgent}
                  onChange={(e) => setSelectedAgent(e.target.value)}
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                >
                  <option value="">— choose an agent —</option>
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </div>
              <p className="text-xs text-muted-foreground">
                Sandbox mode replays the corpus through your detectors
                without burning LLM tokens. Runs in seconds.
              </p>
              <div className="flex items-center justify-end gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setShowStart(false)}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  disabled={!selectedAgent || startRun.isPending}
                  onClick={() =>
                    startRun.mutate({
                      agent_id: selectedAgent,
                      mode: "sandbox",
                    })
                  }
                >
                  {startRun.isPending ? "Starting…" : "Start run"}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading runs…</p>
        ) : runs.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
              <Shield className="h-12 w-12 text-muted-foreground" />
              <p className="text-sm font-medium">No red team runs yet</p>
              <p className="max-w-md text-xs text-muted-foreground">
                A run replays the bundled attack corpus through your detection
                stack and scores how many attacks were caught. Use it for
                weekly regression checks, sales demos, or after any change to
                your custom rules or policies.
              </p>
              {canMutate && (
                <Button
                  size="sm"
                  className="mt-2"
                  onClick={() => setShowStart(true)}
                >
                  <Play className="h-4 w-4" />
                  Run your first test
                </Button>
              )}
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-xs text-muted-foreground">
                    <th className="px-4 py-2 text-left font-medium">Agent</th>
                    <th className="px-4 py-2 text-left font-medium">Mode</th>
                    <th className="px-4 py-2 text-left font-medium">Status</th>
                    <th className="px-4 py-2 text-right font-medium">Score</th>
                    <th className="px-4 py-2 text-center font-medium">Grade</th>
                    <th className="px-4 py-2 text-left font-medium">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr
                      key={run.id}
                      className="border-b border-border last:border-0 hover:bg-muted/40"
                    >
                      <td className="px-4 py-3">
                        <Link
                          to="/red-team/$runId"
                          params={{ runId: run.id }}
                          className="font-medium hover:underline"
                        >
                          {agentName(run.agent_id)}
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {run.mode}
                      </td>
                      <td className="px-4 py-3">
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
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {run.overall_score ?? "—"}
                      </td>
                      <td
                        className={`px-4 py-3 text-center font-bold ${
                          run.grade ? GRADE_COLOR[run.grade] : ""
                        }`}
                      >
                        {run.grade ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {new Date(run.started_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
