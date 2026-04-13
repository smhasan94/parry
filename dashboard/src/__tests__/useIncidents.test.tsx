import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useIncidents, useIncident, useUpdateIncident } from "@/hooks/useIncidents";
import type { ReactNode } from "react";

vi.mock("@/lib/api", () => ({
  api: {
    listIncidents: vi.fn(),
    getIncident: vi.fn(),
    updateIncident: vi.fn(),
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

describe("useIncidents", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.listIncidents and returns paged data", async () => {
    const page = { items: [{ id: "inc-1", title: "Test" }], has_more: false, next_cursor: null };
    vi.mocked(api.listIncidents).mockResolvedValue(page as any);

    const { result } = renderHook(() => useIncidents(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.listIncidents).toHaveBeenCalledOnce();
    expect(result.current.data?.pages[0]).toEqual(page);
  });

  it("passes filter params to api.listIncidents", async () => {
    const page = { items: [], has_more: false, next_cursor: null };
    vi.mocked(api.listIncidents).mockResolvedValue(page as any);

    const { result } = renderHook(
      () => useIncidents({ severity: "high", status: "open" }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.listIncidents).toHaveBeenCalledWith({
      severity: "high",
      status: "open",
      cursor: undefined,
    });
  });

  it("returns error state on failure", async () => {
    vi.mocked(api.listIncidents).mockRejectedValue(new Error("Failed"));
    const { result } = renderHook(() => useIncidents(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("getNextPageParam returns undefined when has_more is false", async () => {
    const page = { items: [], has_more: false, next_cursor: null };
    vi.mocked(api.listIncidents).mockResolvedValue(page as any);

    const { result } = renderHook(() => useIncidents(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.hasNextPage).toBe(false);
  });

  it("hasNextPage is true when has_more is true", async () => {
    const page = { items: [], has_more: true, next_cursor: "cursor-abc" };
    vi.mocked(api.listIncidents).mockResolvedValue(page as any);

    const { result } = renderHook(() => useIncidents(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.hasNextPage).toBe(true);
  });
});

describe("useIncident", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches a single incident by id", async () => {
    const incident = { id: "inc-99", title: "Critical breach" };
    vi.mocked(api.getIncident).mockResolvedValue(incident as any);

    const { result } = renderHook(() => useIncident("inc-99"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.getIncident).toHaveBeenCalledWith("inc-99");
    expect(result.current.data).toEqual(incident);
  });

  it("is disabled when incidentId is empty", () => {
    const { result } = renderHook(() => useIncident(""), { wrapper: makeWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useUpdateIncident", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.updateIncident with correct args", async () => {
    const updated = { id: "inc-1", status: "resolved" };
    vi.mocked(api.updateIncident).mockResolvedValue(updated as any);

    const { result } = renderHook(() => useUpdateIncident(), { wrapper: makeWrapper() });
    result.current.mutate({ incidentId: "inc-1", data: { status: "resolved" } });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.updateIncident).toHaveBeenCalledWith("inc-1", { status: "resolved" });
  });
});
