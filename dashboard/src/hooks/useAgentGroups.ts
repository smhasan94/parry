import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";

export function useAgentGroups() {
  return useQuery({
    queryKey: ["agent-groups"],
    queryFn: () => api.listAgentGroups(),
  });
}

export function useCreateAgentGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      api.createAgentGroup(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-groups"] });
      toast("Group created", "success");
    },
    onError: (err: Error) => {
      toast(err.message || "Failed to create group", "error");
    },
  });
}

export function useDeleteAgentGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (groupId: string) => api.deleteAgentGroup(groupId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-groups"] });
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast("Group deleted", "success");
    },
  });
}

export function useAssignAgentToGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ groupId, agentId }: { groupId: string; agentId: string }) =>
      api.assignAgentToGroup(groupId, agentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-groups"] });
      qc.invalidateQueries({ queryKey: ["agents"] });
      toast("Agent assigned to group", "success");
    },
  });
}
