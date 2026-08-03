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

export function useReviewClassification() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["discovery"] });
    // An approved tier changes the register and the FRIA obligation, so
    // the compliance views are stale too.
    qc.invalidateQueries({ queryKey: ["compliance"] });
  };

  const approve = useMutation({
    mutationFn: (id: string) => api.approveClassification(id),
    onSuccess: () => {
      invalidate();
      toast("Risk tier approved — added to the AI Act register", "success");
    },
    onError: () => toast("Could not approve this classification", "error"),
  });

  const reject = useMutation({
    mutationFn: (id: string) => api.rejectClassification(id),
    onSuccess: () => {
      invalidate();
      toast("Proposed tier rejected", "success");
    },
    onError: () => toast("Could not reject this classification", "error"),
  });

  return { approve, reject };
}
