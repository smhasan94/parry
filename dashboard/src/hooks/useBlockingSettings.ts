import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";

export type ResponseScanMode = "off" | "redact" | "block";

export function useBlockingSettings() {
  return useQuery({
    queryKey: ["blocking-settings"],
    queryFn: () => api.getBlockingSettings(),
  });
}

export function useUpdateBlockingSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      api.updateBlockingSettings({ blocking_enabled: enabled }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["blocking-settings"] });
      toast(
        data.blocking_enabled ? "Blocking mode enabled" : "Blocking mode disabled",
        "success",
      );
    },
    onError: (err: Error) => {
      toast(err.message || "Failed to update blocking mode", "error");
    },
  });
}

export function useResponseScanSettings() {
  return useQuery({
    queryKey: ["response-scan-settings"],
    queryFn: () => api.getResponseScanSettings(),
  });
}

export function useUpdateResponseScanSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mode: ResponseScanMode) =>
      api.updateResponseScanSettings({ response_scan_mode: mode }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["response-scan-settings"] });
      toast(`Response scanning: ${data.response_scan_mode}`, "success");
    },
    onError: (err: Error) => {
      toast(err.message || "Failed to update response scan mode", "error");
    },
  });
}
