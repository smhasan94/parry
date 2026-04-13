import { useQuery } from "@tanstack/react-query";
import { api, type OrgSpendSummary } from "@/lib/api";

export function useOrgSpend() {
  return useQuery<OrgSpendSummary>({
    queryKey: ["org-spend-summary"],
    queryFn: () => api.getOrgSpendSummary(),
    refetchInterval: 30_000,
  });
}
