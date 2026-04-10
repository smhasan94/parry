import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";

export function usePosture() {
  return useQuery({
    queryKey: ["compliance", "posture"],
    queryFn: () => api.getCompliancePosture(),
  });
}

export function useAISystems(riskLevel?: string) {
  return useQuery({
    queryKey: ["compliance", "systems", riskLevel],
    queryFn: () => api.listAISystems(riskLevel),
  });
}

export function useAISystem(systemId: string) {
  return useQuery({
    queryKey: ["compliance", "systems", systemId],
    queryFn: () => api.getAISystem(systemId),
    enabled: !!systemId,
  });
}

export function useCreateAISystem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof api.createAISystem>[0]) =>
      api.createAISystem(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["compliance", "systems"] });
      qc.invalidateQueries({ queryKey: ["compliance", "posture"] });
      toast("AI system registered", "success");
    },
  });
}

export function useUpdateAISystem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      systemId,
      data,
    }: {
      systemId: string;
      data: Record<string, unknown>;
    }) => api.updateAISystem(systemId, data),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["compliance", "systems"] });
      qc.invalidateQueries({
        queryKey: ["compliance", "systems", vars.systemId],
      });
      qc.invalidateQueries({ queryKey: ["compliance", "posture"] });
      toast("AI system updated", "success");
    },
  });
}

export function useDeleteAISystem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (systemId: string) => api.deleteAISystem(systemId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["compliance", "systems"] });
      qc.invalidateQueries({ queryKey: ["compliance", "posture"] });
      toast("AI system removed", "success");
    },
  });
}

export function useSuppliers(systemId: string) {
  return useQuery({
    queryKey: ["compliance", "suppliers", systemId],
    queryFn: () => api.listSuppliers(systemId),
    enabled: !!systemId,
  });
}

export function useSystemFRIAs(systemId: string) {
  return useQuery({
    queryKey: ["compliance", "fria", systemId],
    queryFn: () => api.listSystemFRIAs(systemId),
    enabled: !!systemId,
  });
}

export function useCreateFRIA() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (systemId: string) => api.createFRIA(systemId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["compliance", "fria"] });
      qc.invalidateQueries({ queryKey: ["compliance", "systems"] });
      qc.invalidateQueries({ queryKey: ["compliance", "posture"] });
      toast("FRIA draft created", "success");
    },
  });
}

export function useApproveFRIA() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      friaId,
      approverTitle,
    }: {
      friaId: string;
      approverTitle?: string;
    }) => api.approveFRIA(friaId, approverTitle),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["compliance"] });
      toast("FRIA approved", "success");
    },
  });
}

export function useSeriousIncidents(unreportedOnly = false) {
  return useQuery({
    queryKey: ["compliance", "serious-incidents", unreportedOnly],
    queryFn: () => api.listSeriousIncidents(unreportedOnly),
  });
}

export function useCreateSeriousReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      incidentId,
      systemId,
    }: {
      incidentId: string;
      systemId?: string;
    }) => api.createSeriousReport(incidentId, systemId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["compliance", "serious-incidents"] });
      qc.invalidateQueries({ queryKey: ["compliance", "posture"] });
      toast("Serious incident report created", "success");
    },
  });
}

export function useFinalizeSeriousReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reportId: string) => api.finalizeSeriousReport(reportId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["compliance"] });
      toast("Report finalized and submitted", "success");
    },
  });
}

export function useRequestAuditorBundle() {
  return useMutation({
    mutationFn: ({
      periodStart,
      periodEnd,
    }: {
      periodStart?: string;
      periodEnd?: string;
    }) => api.requestAuditorBundle(periodStart, periodEnd),
    onSuccess: () => {
      toast("Auditor bundle generation started", "success");
    },
    onError: (err: Error) => {
      toast(err.message || "Failed to generate bundle", "error");
    },
  });
}
