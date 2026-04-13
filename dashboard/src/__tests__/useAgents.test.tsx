import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAgents, useAgent, useCreateAgent, useDeleteAgent } from "@/hooks/useAgents";
import type { ReactNode } from "react";

// Mock the api module
vi.mock("@/lib/api", () => ({
  api: {
    listAgents: vi.fn(),
    getAgent: vi.fn(),
    createAgent: vi.fn(),
    updateAgent: vi.fn(),
    deleteAgent: vi.fn(),
    recomputeBaseline: vi.fn(),
    recomputeAllBaselines: vi.fn(),
  },
}));

vi.mock("@/components/ui/toast", () => ({
  toast: vi.fn(),
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

describe("useAgents", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.listAgents and returns data", async () => {
    const agents = [{ id: "a1", name: "Agent One" }];
    vi.mocked(api.listAgents).mockResolvedValue(agents as any);

    const { result } = renderHook(() => useAgents(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.listAgents).toHaveBeenCalledOnce();
    expect(result.current.data).toEqual(agents);
  });

  it("uses queryKey ['agents']", async () => {
    vi.mocked(api.listAgents).mockResolvedValue([]);
    const { result } = renderHook(() => useAgents(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.listAgents).toHaveBeenCalledOnce();
  });

  it("returns loading state initially", () => {
    vi.mocked(api.listAgents).mockReturnValue(new Promise(() => {})); // never resolves
    const { result } = renderHook(() => useAgents(), { wrapper: makeWrapper() });
    expect(result.current.isLoading).toBe(true);
  });

  it("returns error state on api failure", async () => {
    vi.mocked(api.listAgents).mockRejectedValue(new Error("Network error"));
    const { result } = renderHook(() => useAgents(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Error);
  });
});

describe("useAgent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.getAgent with the provided agentId", async () => {
    const agent = { id: "agent-123", name: "My Agent" };
    vi.mocked(api.getAgent).mockResolvedValue(agent as any);

    const { result } = renderHook(() => useAgent("agent-123"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.getAgent).toHaveBeenCalledWith("agent-123");
    expect(result.current.data).toEqual(agent);
  });

  it("is disabled when agentId is empty string", () => {
    const { result } = renderHook(() => useAgent(""), { wrapper: makeWrapper() });
    // enabled: false means fetchStatus is idle
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useCreateAgent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.createAgent with the provided data", async () => {
    const newAgent = { id: "new-1", name: "New Agent" };
    vi.mocked(api.createAgent).mockResolvedValue(newAgent as any);

    const { result } = renderHook(() => useCreateAgent(), { wrapper: makeWrapper() });
    result.current.mutate({ name: "New Agent", description: "Test" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.createAgent).toHaveBeenCalledWith({ name: "New Agent", description: "Test" });
  });
});

describe("useDeleteAgent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.deleteAgent with the agentId", async () => {
    vi.mocked(api.deleteAgent).mockResolvedValue(undefined as any);

    const { result } = renderHook(() => useDeleteAgent(), { wrapper: makeWrapper() });
    result.current.mutate("agent-456");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.deleteAgent).toHaveBeenCalledWith("agent-456");
  });
});
