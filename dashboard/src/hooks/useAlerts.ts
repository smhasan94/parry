import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AlertConfig } from "@/lib/api";

export function useAlertConfig() {
  return useQuery<AlertConfig>({
    queryKey: ["alert-config"],
    queryFn: () => api.getAlertConfig(),
  });
}

export function useUpdateAlertConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      slack_webhook_url?: string;
      alert_emails?: string[];
      webhook_url?: string;
      webhook_headers?: Record<string, string>;
      min_severity?: string;
    }) => api.updateAlertConfig(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-config"] }),
  });
}

export function useDeleteAlertConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.deleteAlertConfig(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-config"] }),
  });
}

export function useTestAlert() {
  return useMutation({
    mutationFn: (channel: "slack" | "email" | "webhook") => api.sendTestAlert(channel),
  });
}
