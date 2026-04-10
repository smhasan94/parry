import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";

export function useAgentPermissions(agentId: string) {
  return useQuery({
    queryKey: ["permissions", agentId],
    queryFn: () => api.getAgentPermissions(agentId),
    enabled: !!agentId,
  });
}

export function useSetAgentPermissions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      agentId,
      data,
    }: {
      agentId: string;
      data: {
        mode: string;
        default_action: string;
        allowed_tools: string[];
        blocked_tools: string[];
      };
    }) => api.setAgentPermissions(agentId, data),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["permissions", vars.agentId] });
      toast("Permissions updated", "success");
    },
    onError: (err: Error) => {
      toast(err.message || "Failed to update permissions", "error");
    },
  });
}

export function useDeleteAgentPermissions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) => api.deleteAgentPermissions(agentId),
    onSuccess: (_data, agentId) => {
      qc.invalidateQueries({ queryKey: ["permissions", agentId] });
      toast("Permissions removed — agent uses org defaults", "success");
    },
  });
}
