import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type AgentBudgetResponse,
  type AgentSpendResponse,
} from "@/lib/api";
import { toast } from "@/components/ui/toast";

export function useAgentSpend(agentId: string | undefined) {
  return useQuery<AgentSpendResponse>({
    queryKey: ["agent-spend", agentId],
    queryFn: () => api.getAgentSpend(agentId!),
    enabled: !!agentId,
    refetchInterval: 30_000,
  });
}

export function useAgentBudgets(agentId?: string) {
  return useQuery<AgentBudgetResponse[]>({
    queryKey: ["budgets", agentId ?? "all"],
    queryFn: () => api.listBudgets(agentId),
  });
}

export function useSetBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      agent_id?: string | null;
      period: "hour" | "day" | "month";
      cap_usd: number;
      enabled?: boolean;
    }) => api.upsertBudget(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
      qc.invalidateQueries({ queryKey: ["agent-spend"] });
      toast("Budget saved", "success");
    },
    onError: (err: Error) => toast(err.message, "error"),
  });
}

export function useDeleteBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (budgetId: string) => api.deleteBudget(budgetId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
      qc.invalidateQueries({ queryKey: ["agent-spend"] });
      toast("Budget removed", "success");
    },
    onError: (err: Error) => toast(err.message, "error"),
  });
}
