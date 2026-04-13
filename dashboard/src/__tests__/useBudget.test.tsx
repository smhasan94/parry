import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAgentSpend, useAgentBudgets, useSetBudget, useDeleteBudget } from "@/hooks/useBudget";
import type { ReactNode } from "react";

vi.mock("@/lib/api", () => ({
  api: {
    getAgentSpend: vi.fn(),
    listBudgets: vi.fn(),
    upsertBudget: vi.fn(),
    deleteBudget: vi.fn(),
  },
}));

vi.mock("@/components/ui/toast", () => ({
  toast: vi.fn(),
}));

import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useAgentSpend", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches spend data for an agent", async () => {
    const spend = {
      period_spend: { hour: 0.12, day: 1.5, month: 30.0 },
      budgets: [],
    };
    vi.mocked(api.getAgentSpend).mockResolvedValue(spend as any);

    const { result } = renderHook(() => useAgentSpend("agent-1"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.getAgentSpend).toHaveBeenCalledWith("agent-1");
    expect(result.current.data).toEqual(spend);
  });

  it("is disabled when agentId is undefined", () => {
    const { result } = renderHook(() => useAgentSpend(undefined), { wrapper: makeWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("returns error state on failure", async () => {
    vi.mocked(api.getAgentSpend).mockRejectedValue(new Error("Not found"));
    const { result } = renderHook(() => useAgentSpend("agent-bad"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useAgentBudgets", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches budgets for an agent", async () => {
    const budgets = [{ id: "b-1", period: "day", cap_usd: 10.0 }];
    vi.mocked(api.listBudgets).mockResolvedValue(budgets as any);

    const { result } = renderHook(() => useAgentBudgets("agent-1"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.listBudgets).toHaveBeenCalledWith("agent-1");
    expect(result.current.data).toEqual(budgets);
  });

  it("fetches org-wide budgets when no agentId provided", async () => {
    vi.mocked(api.listBudgets).mockResolvedValue([]);

    const { result } = renderHook(() => useAgentBudgets(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.listBudgets).toHaveBeenCalledWith(undefined);
  });
});

describe("useSetBudget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.upsertBudget with correct data", async () => {
    vi.mocked(api.upsertBudget).mockResolvedValue({ id: "b-new" } as any);

    const { result } = renderHook(() => useSetBudget(), { wrapper: makeWrapper() });
    result.current.mutate({ agent_id: "agent-1", period: "day", cap_usd: 5.0 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.upsertBudget).toHaveBeenCalledWith({
      agent_id: "agent-1",
      period: "day",
      cap_usd: 5.0,
    });
  });

  it("shows success toast after saving", async () => {
    vi.mocked(api.upsertBudget).mockResolvedValue({ id: "b" } as any);

    const { result } = renderHook(() => useSetBudget(), { wrapper: makeWrapper() });
    result.current.mutate({ period: "month", cap_usd: 100 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast).toHaveBeenCalledWith("Budget saved", "success");
  });
});

describe("useDeleteBudget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.deleteBudget with the budgetId", async () => {
    vi.mocked(api.deleteBudget).mockResolvedValue(undefined as any);

    const { result } = renderHook(() => useDeleteBudget(), { wrapper: makeWrapper() });
    result.current.mutate("budget-xyz");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.deleteBudget).toHaveBeenCalledWith("budget-xyz");
  });

  it("shows success toast after deletion", async () => {
    vi.mocked(api.deleteBudget).mockResolvedValue(undefined as any);

    const { result } = renderHook(() => useDeleteBudget(), { wrapper: makeWrapper() });
    result.current.mutate("b-del");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast).toHaveBeenCalledWith("Budget removed", "success");
  });
});
