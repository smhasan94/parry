import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type RedTeamRunDetail, type RedTeamRunSummary } from "@/lib/api";
import { toast } from "@/components/ui/toast";
import { useNavigate } from "@tanstack/react-router";

const POLL_INTERVAL_MS = 2000;

export function useRedTeamRuns(agentId?: string) {
  return useQuery<RedTeamRunSummary[]>({
    queryKey: ["red-team", "runs", agentId ?? "all"],
    queryFn: () => api.listRedTeamRuns(agentId),
  });
}

/**
 * Fetches a single run. Auto-polls every 2s while status is queued
 * or running, stops polling on completed/failed.
 */
export function useRedTeamRun(runId: string | undefined) {
  return useQuery<RedTeamRunDetail>({
    queryKey: ["red-team", "run", runId],
    queryFn: () => api.getRedTeamRun(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running"
        ? POLL_INTERVAL_MS
        : false;
    },
  });
}

export function useStartRedTeamRun() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: (body: { agent_id: string; mode: "sandbox" | "live" }) =>
      api.startRedTeamRun(body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["red-team", "runs"] });
      toast("Red team run started", "success");
      navigate({ to: "/red-team/$runId", params: { runId: data.run_id } });
    },
    onError: (err: Error) => toast(err.message, "error"),
  });
}

export function useRedTeamCorpus() {
  return useQuery({
    queryKey: ["red-team", "corpus"],
    queryFn: () => api.getRedTeamCorpus(),
  });
}
