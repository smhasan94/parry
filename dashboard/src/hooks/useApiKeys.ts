import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useApiKeys() {
  return useQuery({
    queryKey: ["api-keys"],
    queryFn: () => api.listApiKeys(),
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.createApiKey(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) => api.revokeApiKey(keyId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });
}
