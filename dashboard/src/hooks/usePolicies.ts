import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Policy } from "@/lib/types";

export function usePolicies() {
  return useQuery({
    queryKey: ["policies"],
    queryFn: () => api.listPolicies(),
  });
}

export function usePolicy(policyId: string) {
  return useQuery({
    queryKey: ["policies", policyId],
    queryFn: () => api.getPolicy(policyId),
    enabled: !!policyId,
  });
}

export function useCreatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Policy>) => api.createPolicy(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["policies"] }),
  });
}

export function useUpdatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ policyId, data }: { policyId: string; data: Partial<Policy> }) =>
      api.updatePolicy(policyId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["policies"] }),
  });
}

export function useDeletePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (policyId: string) => api.deletePolicy(policyId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["policies"] }),
  });
}
