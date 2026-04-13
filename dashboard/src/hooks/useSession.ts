import { useQuery } from "@tanstack/react-query";
import { api, type SessionReplay, type SessionSummary } from "@/lib/api";
import type { Incident } from "@/lib/types";

export function useSession(sessionId: string | undefined) {
  return useQuery<SessionReplay>({
    queryKey: ["session", sessionId],
    queryFn: () => api.getSession(sessionId!),
    enabled: !!sessionId,
    // Ongoing sessions appear as "Live"; poll every 5s so the replay
    // picks up new events without a manual refresh. Completed
    // sessions never mutate, so the staleTime protects those from
    // unnecessary refetches.
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.session.ended_at ? false : 5000;
    },
    staleTime: 10_000,
  });
}

export function useAgentSessions(agentId: string | undefined, limit = 20) {
  return useQuery<SessionSummary[]>({
    queryKey: ["agent-sessions", agentId, limit],
    queryFn: () => api.listAgentSessions(agentId!, limit),
    enabled: !!agentId,
  });
}

export function useSessionIncidents(sessionId: string | undefined) {
  return useQuery<{ incidents: Incident[]; next_cursor: string | null; has_more: boolean }>({
    queryKey: ["session-incidents", sessionId],
    queryFn: () => api.getSessionIncidents(sessionId!),
    enabled: !!sessionId,
    staleTime: 30_000,
  });
}
