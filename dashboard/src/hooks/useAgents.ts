import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";
import type { Agent } from "@/lib/types";

export function useAgents() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => api.listAgents(),
  });
}

export function useAgent(agentId: string) {
  return useQuery({
    queryKey: ["agents", agentId],
    queryFn: () => api.getAgent(agentId),
    enabled: !!agentId,
  });
}

export function useCreateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) => api.createAgent(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast("Agent created", "success");
    },
  });
}

export function useUpdateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, data }: { agentId: string; data: Partial<Agent> }) =>
      api.updateAgent(agentId, data),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      qc.invalidateQueries({ queryKey: ["agents", vars.agentId] });
    },
  });
}

export function useRecomputeBaseline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) => api.recomputeBaseline(agentId),
    onSuccess: (_data, agentId) => {
      qc.invalidateQueries({ queryKey: ["agents", agentId] });
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast("Baseline recomputed", "success");
    },
    onError: (err: Error) => {
      toast(err.message || "Failed to recompute baseline", "error");
    },
  });
}

export function useRecomputeAllBaselines() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.recomputeAllBaselines(),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      const parts = [`${data.recomputed} recomputed`];
      if (data.skipped) parts.push(`${data.skipped} skipped`);
      if (data.errored) parts.push(`${data.errored} errored`);
      toast(`Baselines: ${parts.join(", ")}`, data.errored ? "error" : "success");
    },
    onError: (err: Error) => {
      toast(err.message || "Failed to recompute baselines", "error");
    },
  });
}

export function useDeleteAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) => api.deleteAgent(agentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast("Agent deleted", "success");
    },
  });
}
