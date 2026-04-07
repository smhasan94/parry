import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type DetectorConfig } from "@/lib/api";

export function useDetectorConfig() {
  return useQuery<DetectorConfig>({
    queryKey: ["detector-config"],
    queryFn: () => api.getDetectorConfig(),
  });
}

export function useDefaultDetectorConfig() {
  return useQuery<DetectorConfig>({
    queryKey: ["detector-config", "defaults"],
    queryFn: () => api.getDefaultDetectorConfig(),
    staleTime: Infinity, // defaults never change at runtime
  });
}

export function useUpdateDetectorConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      config: Record<string, { trigger_threshold?: number; enabled?: boolean }>
    ) => api.updateDetectorConfig(config),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["detector-config"] }),
  });
}

export function useResetDetectorConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.resetDetectorConfig(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["detector-config"] }),
  });
}
