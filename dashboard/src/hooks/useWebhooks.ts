import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";

export function useWebhookEndpoints() {
  return useQuery({
    queryKey: ["webhooks", "endpoints"],
    queryFn: () => api.listWebhookEndpoints(),
  });
}

export function useCreateWebhookEndpoint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { url: string; event_types: string[]; description?: string }) =>
      api.createWebhookEndpoint(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["webhooks"] });
      toast("Webhook endpoint created", "success");
    },
    onError: (err: Error) => {
      toast(err.message || "Failed to create endpoint", "error");
    },
  });
}

export function useDeleteWebhookEndpoint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (endpointId: string) => api.deleteWebhookEndpoint(endpointId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["webhooks"] });
      toast("Webhook endpoint deleted", "success");
    },
  });
}

export function useTestWebhookEndpoint() {
  return useMutation({
    mutationFn: (endpointId: string) => api.testWebhookEndpoint(endpointId),
    onSuccess: () => {
      toast("Test webhook sent", "success");
    },
    onError: (err: Error) => {
      toast(err.message || "Test failed", "error");
    },
  });
}

export function useWebhookDeliveries(endpointId: string) {
  return useQuery({
    queryKey: ["webhooks", "deliveries", endpointId],
    queryFn: () => api.listWebhookDeliveries(endpointId),
    enabled: !!endpointId,
  });
}
