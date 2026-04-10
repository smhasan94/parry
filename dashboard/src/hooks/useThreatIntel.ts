import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";

export function useThreatFeed() {
  return useQuery({
    queryKey: ["threat-intel", "feed"],
    queryFn: () => api.getThreatFeed(),
    refetchInterval: 30_000,
  });
}

export function useThreatFeedStats() {
  return useQuery({
    queryKey: ["threat-intel", "stats"],
    queryFn: () => api.getThreatFeedStats(),
    refetchInterval: 60_000,
  });
}

export function useUpdateThreatSharing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sharing: boolean) => api.updateThreatSharingSettings(sharing),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["threat-intel"] });
      toast("Sharing settings updated", "success");
    },
    onError: (err: Error) => {
      toast(err.message || "Failed to update settings", "error");
    },
  });
}
