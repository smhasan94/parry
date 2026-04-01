import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { IncidentStatus, Severity } from "@/lib/types";

export function useIncidents(filters?: { severity?: Severity; status?: IncidentStatus }) {
  return useQuery({
    queryKey: ["incidents", filters],
    queryFn: () => api.listIncidents(filters),
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
