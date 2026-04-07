import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useAuditLog(filters?: {
  action?: string;
  resource_type?: string;
  resource_id?: string;
}) {
  return useInfiniteQuery({
    queryKey: ["audit-log", filters],
    queryFn: ({ pageParam }) =>
      api.listAuditLog({
        ...filters,
        cursor: pageParam as string | undefined,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

/**
 * One-shot history query for a specific resource (e.g. an incident).
 * `enabled=false` defers the fetch until the section is expanded.
 */
export function useResourceHistory(
  resourceType: string,
  resourceId: string,
  enabled: boolean
) {
  return useQuery({
    queryKey: ["audit-log", "resource", resourceType, resourceId],
    queryFn: () =>
      api.listAuditLog({ resource_type: resourceType, resource_id: resourceId }),
    enabled,
    staleTime: 10_000,
  });
}
