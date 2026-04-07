import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CustomRule, type CustomRuleInput } from "@/lib/api";
import { toast } from "@/components/ui/toast";

export function useCustomRules() {
  return useQuery<CustomRule[]>({
    queryKey: ["custom-rules"],
    queryFn: () => api.listCustomRules(),
  });
}

export function useCreateCustomRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CustomRuleInput) => api.createCustomRule(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["custom-rules"] });
      toast("Custom rule created", "success");
    },
    onError: (err: Error) => toast(err.message, "error"),
  });
}

export function useUpdateCustomRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      ruleId,
      body,
    }: {
      ruleId: string;
      body: Partial<CustomRuleInput>;
    }) => api.updateCustomRule(ruleId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["custom-rules"] });
    },
    onError: (err: Error) => toast(err.message, "error"),
  });
}

export function useDeleteCustomRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ruleId: string) => api.deleteCustomRule(ruleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["custom-rules"] });
      toast("Custom rule deleted", "success");
    },
    onError: (err: Error) => toast(err.message, "error"),
  });
}

export function useTestCustomRule() {
  return useMutation({
    mutationFn: (body: { pattern: string; sample: string }) =>
      api.testCustomRule(body),
  });
}
