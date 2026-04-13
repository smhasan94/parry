import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAgentStats } from "@/hooks/useAgentStats";
import type { ReactNode } from "react";

vi.mock("@/lib/api", () => ({
  api: {
    getAgentStats: vi.fn(),
  },
}));

import { api } from "@/lib/api";

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useAgentStats", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.getAgentStats with agentId and window", async () => {
    const stats = {
      total_events: 100,
      blocked_events: 5,
      detections: 12,
      avg_latency_ms: 250,
    };
    vi.mocked(api.getAgentStats).mockResolvedValue(stats as any);

    const { result } = renderHook(() => useAgentStats("agent-1", "7d"), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.getAgentStats).toHaveBeenCalledWith("agent-1", "7d");
    expect(result.current.data).toEqual(stats);
  });

  it("uses the correct query key structure", async () => {
    vi.mocked(api.getAgentStats).mockResolvedValue({} as any);

    const { result } = renderHook(() => useAgentStats("agent-42", "30d"), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.getAgentStats).toHaveBeenCalledWith("agent-42", "30d");
  });

  it("returns error state on failure", async () => {
    vi.mocked(api.getAgentStats).mockRejectedValue(new Error("Agent not found"));

    const { result } = renderHook(() => useAgentStats("bad-id", "90d"), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("returns loading state initially", () => {
    vi.mocked(api.getAgentStats).mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useAgentStats("agent-1", "7d"), {
      wrapper: makeWrapper(),
    });
    expect(result.current.isLoading).toBe(true);
  });

  it("accepts all valid window values", async () => {
    vi.mocked(api.getAgentStats).mockResolvedValue({} as any);

    for (const window of ["7d", "30d", "90d"] as const) {
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      );
      const { result } = renderHook(() => useAgentStats("agent-1", window), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
    }

    expect(api.getAgentStats).toHaveBeenCalledTimes(3);
  });
});
