import { useQuery } from "@tanstack/react-query";
import { api, type AgentStats } from "@/lib/api";

export type AgentStatsWindow = "7d" | "30d" | "90d";

export function useAgentStats(agentId: string, window: AgentStatsWindow) {
  return useQuery<AgentStats>({
    queryKey: ["agents", agentId, "stats", window],
    queryFn: () => api.getAgentStats(agentId, window),
    // Match the backend's 5 minute Redis TTL so we don't refetch
    // constantly while the user flips between tabs.
    staleTime: 5 * 60 * 1000,
  });
}
