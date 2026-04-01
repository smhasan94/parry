import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useEvents(agentId: string, cursor?: string) {
  return useQuery({
    queryKey: ["events", agentId, cursor],
    queryFn: () => api.listEvents(agentId, cursor),
    enabled: !!agentId,
  });
}

export function useEvent(eventId: string) {
  return useQuery({
    queryKey: ["events", "detail", eventId],
    queryFn: () => api.getEvent(eventId),
    enabled: !!eventId,
  });
}
