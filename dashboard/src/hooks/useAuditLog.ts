import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useAuditLog(filters?: { action?: string; resource_type?: string }) {
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
