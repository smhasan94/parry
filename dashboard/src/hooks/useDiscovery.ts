import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";

export function useShadowAI(limit = 100) {
  return useQuery({
    queryKey: ["discovery", "shadow", limit],
    queryFn: () => api.listShadowAI(limit),
  });
}

export function useSyncOkta() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ oktaDomain, apiToken }: { oktaDomain: string; apiToken: string }) =>
      api.syncOkta(oktaDomain, apiToken),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["discovery"] });
      qc.invalidateQueries({ queryKey: ["compliance"] });
      toast(
        `Scanned ${result.processed} grants — ${result.matched} matched the catalog`,
        "success",
      );
    },
    onError: () => toast("Okta scan failed — check the domain and token", "error"),
  });
}
