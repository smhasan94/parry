import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/hooks/useApiKeys";
import type { ReactNode } from "react";

vi.mock("@/lib/api", () => ({
  api: {
    listApiKeys: vi.fn(),
    createApiKey: vi.fn(),
    revokeApiKey: vi.fn(),
  },
}));

vi.mock("@/components/ui/toast", () => ({
  toast: vi.fn(),
}));

import { api } from "@/lib/api";
import { toast } from "@/components/ui/toast";

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useApiKeys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.listApiKeys and returns data", async () => {
    const keys = [{ id: "key-1", name: "Prod Key", prefix: "sk_" }];
    vi.mocked(api.listApiKeys).mockResolvedValue(keys as any);

    const { result } = renderHook(() => useApiKeys(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.listApiKeys).toHaveBeenCalledOnce();
    expect(result.current.data).toEqual(keys);
  });

  it("returns error state on api failure", async () => {
    vi.mocked(api.listApiKeys).mockRejectedValue(new Error("Unauthorized"));
    const { result } = renderHook(() => useApiKeys(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useCreateApiKey", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.createApiKey with the key name", async () => {
    const created = { id: "key-new", name: "My Key", key: "sk_test_abc" };
    vi.mocked(api.createApiKey).mockResolvedValue(created as any);

    const { result } = renderHook(() => useCreateApiKey(), { wrapper: makeWrapper() });
    result.current.mutate("My Key");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.createApiKey).toHaveBeenCalledWith("My Key");
  });

  it("shows success toast after creating", async () => {
    vi.mocked(api.createApiKey).mockResolvedValue({ id: "k", name: "N", key: "sk_" } as any);
    const { result } = renderHook(() => useCreateApiKey(), { wrapper: makeWrapper() });
    result.current.mutate("Test");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast).toHaveBeenCalledWith("API key created", "success");
  });
});

describe("useRevokeApiKey", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.revokeApiKey with the keyId", async () => {
    vi.mocked(api.revokeApiKey).mockResolvedValue(undefined as any);

    const { result } = renderHook(() => useRevokeApiKey(), { wrapper: makeWrapper() });
    result.current.mutate("key-to-revoke");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.revokeApiKey).toHaveBeenCalledWith("key-to-revoke");
  });

  it("shows success toast after revoking", async () => {
    vi.mocked(api.revokeApiKey).mockResolvedValue(undefined as any);
    const { result } = renderHook(() => useRevokeApiKey(), { wrapper: makeWrapper() });
    result.current.mutate("key-123");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast).toHaveBeenCalledWith("API key revoked", "success");
  });
});
