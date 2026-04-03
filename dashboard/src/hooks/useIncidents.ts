import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { IncidentStatus, Severity } from "@/lib/types";

export function useIncidents(filters?: { severity?: Severity; status?: IncidentStatus }) {
  return useInfiniteQuery({
    queryKey: ["incidents", filters],
    queryFn: ({ pageParam }) => api.listIncidents({ ...filters, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
  });
}

export function useIncident(incidentId: string) {
  return useQuery({
    queryKey: ["incidents", incidentId],
    queryFn: () => api.getIncident(incidentId),
    enabled: !!incidentId,
  });
}

export function useUpdateIncident() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      incidentId,
      data,
    }: {
      incidentId: string;
      data: { status?: IncidentStatus; title?: string };
    }) => api.updateIncident(incidentId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["incidents"] }),
  });
}
