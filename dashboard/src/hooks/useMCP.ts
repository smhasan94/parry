import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type MCPServerDetail,
  type MCPServerSummary,
  type MCPTrustLevel,
} from "@/lib/api";
import { toast } from "@/components/ui/toast";

export function useMCPServers() {
  return useQuery<MCPServerSummary[]>({
    queryKey: ["mcp", "servers"],
    queryFn: () => api.listMCPServers(),
  });
}

export function useMCPServer(serverId: string | undefined) {
  return useQuery<MCPServerDetail>({
    queryKey: ["mcp", "server", serverId],
    queryFn: () => api.getMCPServer(serverId!),
    enabled: !!serverId,
  });
}

export function useSetMCPServerTrust() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      serverId,
      trustLevel,
    }: {
      serverId: string;
      trustLevel: MCPTrustLevel;
    }) => api.updateMCPServer(serverId, { trust_level: trustLevel }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["mcp", "servers"] });
      qc.invalidateQueries({ queryKey: ["mcp", "server", vars.serverId] });
      toast(`Trust level updated to ${vars.trustLevel}`, "success");
    },
    onError: (err: Error) => toast(err.message, "error"),
  });
}
