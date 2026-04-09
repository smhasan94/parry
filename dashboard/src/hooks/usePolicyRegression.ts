import { useMutation } from "@tanstack/react-query";
import { api, type SimulationReport } from "@/lib/api";
import { toast } from "@/components/ui/toast";

export interface SimulateRuleRequest {
  pattern: string;
  target: "prompt" | "response" | "both";
  days_back?: number;
  sample_limit?: number;
}

export interface SimulatePolicyRequest {
  policy: Record<string, unknown>;
  days_back?: number;
  sample_limit?: number;
}

/**
 * Mutation wrapper around POST /custom-rules/simulate.
 *
 * We use a mutation rather than a query because the simulation is
 * write-shaped (rate-limited, audit-logged) even though it's read-only
 * server-side. The caller debounces the trigger.
 */
export function useSimulateCustomRule() {
  return useMutation<SimulationReport, Error, SimulateRuleRequest>({
    mutationFn: (body) => api.simulateCustomRule(body),
    onError: (err) => toast(err.message, "error"),
  });
}

export function useSimulatePolicy() {
  return useMutation<SimulationReport, Error, SimulatePolicyRequest>({
    mutationFn: (body) => api.simulatePolicy(body),
    onError: (err) => toast(err.message, "error"),
  });
}
