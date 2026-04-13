import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { usePolicies, usePolicy, useCreatePolicy, useDeletePolicy } from "@/hooks/usePolicies";
import type { ReactNode } from "react";

vi.mock("@/lib/api", () => ({
  api: {
    listPolicies: vi.fn(),
    getPolicy: vi.fn(),
    createPolicy: vi.fn(),
    updatePolicy: vi.fn(),
    deletePolicy: vi.fn(),
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

describe("usePolicies", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.listPolicies and returns data", async () => {
    const policies = [{ id: "p-1", name: "Strict Policy" }];
    vi.mocked(api.listPolicies).mockResolvedValue(policies as any);

    const { result } = renderHook(() => usePolicies(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.listPolicies).toHaveBeenCalledOnce();
    expect(result.current.data).toEqual(policies);
  });

  it("returns error state on failure", async () => {
    vi.mocked(api.listPolicies).mockRejectedValue(new Error("Server error"));
    const { result } = renderHook(() => usePolicies(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("returns empty array when no policies exist", async () => {
    vi.mocked(api.listPolicies).mockResolvedValue([]);
    const { result } = renderHook(() => usePolicies(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});

describe("usePolicy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches a single policy by id", async () => {
    const policy = { id: "p-42", name: "My Policy" };
    vi.mocked(api.getPolicy).mockResolvedValue(policy as any);

    const { result } = renderHook(() => usePolicy("p-42"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.getPolicy).toHaveBeenCalledWith("p-42");
    expect(result.current.data).toEqual(policy);
  });

  it("is disabled when policyId is empty", () => {
    const { result } = renderHook(() => usePolicy(""), { wrapper: makeWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useCreatePolicy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.createPolicy with the provided data", async () => {
    const created = { id: "p-new", name: "New Policy" };
    vi.mocked(api.createPolicy).mockResolvedValue(created as any);

    const { result } = renderHook(() => useCreatePolicy(), { wrapper: makeWrapper() });
    result.current.mutate({ name: "New Policy" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.createPolicy).toHaveBeenCalledWith({ name: "New Policy" });
  });
});

describe("useDeletePolicy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.deletePolicy with the policyId", async () => {
    vi.mocked(api.deletePolicy).mockResolvedValue(undefined as any);

    const { result } = renderHook(() => useDeletePolicy(), { wrapper: makeWrapper() });
    result.current.mutate("p-to-delete");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.deletePolicy).toHaveBeenCalledWith("p-to-delete");
  });
});
