import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useEvents(agentId: string) {
  return useInfiniteQuery({
    queryKey: ["events", agentId],
    queryFn: ({ pageParam }) => api.listEvents(agentId, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
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
