import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEvents, useEvent } from "@/hooks/useEvents";
import type { ReactNode } from "react";

vi.mock("@/lib/api", () => ({
  api: {
    listEvents: vi.fn(),
    getEvent: vi.fn(),
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

describe("useEvents", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.listEvents with the agentId", async () => {
    const page = { items: [{ id: "evt-1" }], has_more: false, next_cursor: null };
    vi.mocked(api.listEvents).mockResolvedValue(page as any);

    const { result } = renderHook(() => useEvents("agent-abc"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.listEvents).toHaveBeenCalledWith("agent-abc", undefined);
  });

  it("is disabled when agentId is empty", () => {
    const { result } = renderHook(() => useEvents(""), { wrapper: makeWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("returns error state on failure", async () => {
    vi.mocked(api.listEvents).mockRejectedValue(new Error("Network error"));
    const { result } = renderHook(() => useEvents("agent-abc"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("provides hasNextPage false when has_more is false", async () => {
    const page = { items: [], has_more: false, next_cursor: null };
    vi.mocked(api.listEvents).mockResolvedValue(page as any);

    const { result } = renderHook(() => useEvents("agent-abc"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.hasNextPage).toBe(false);
  });

  it("provides hasNextPage true when has_more is true", async () => {
    const page = { items: [], has_more: true, next_cursor: "tok-xyz" };
    vi.mocked(api.listEvents).mockResolvedValue(page as any);

    const { result } = renderHook(() => useEvents("agent-abc"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.hasNextPage).toBe(true);
  });
});

describe("useEvent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches a single event by id", async () => {
    const event = { id: "evt-42", prompt: "hello" };
    vi.mocked(api.getEvent).mockResolvedValue(event as any);

    const { result } = renderHook(() => useEvent("evt-42"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.getEvent).toHaveBeenCalledWith("evt-42");
    expect(result.current.data).toEqual(event);
  });

  it("is disabled when eventId is empty", () => {
    const { result } = renderHook(() => useEvent(""), { wrapper: makeWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
  });
});
