import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAlertConfig, useUpdateAlertConfig, useDeleteAlertConfig, useTestAlert } from "@/hooks/useAlerts";
import type { ReactNode } from "react";

vi.mock("@/lib/api", () => ({
  api: {
    getAlertConfig: vi.fn(),
    updateAlertConfig: vi.fn(),
    deleteAlertConfig: vi.fn(),
    sendTestAlert: vi.fn(),
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

describe("useAlertConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches alert configuration", async () => {
    const config = { slack_webhook_url: "https://hooks.slack.com/abc", min_severity: "high" };
    vi.mocked(api.getAlertConfig).mockResolvedValue(config as any);

    const { result } = renderHook(() => useAlertConfig(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.getAlertConfig).toHaveBeenCalledOnce();
    expect(result.current.data).toEqual(config);
  });

  it("returns error state on failure", async () => {
    vi.mocked(api.getAlertConfig).mockRejectedValue(new Error("Not configured"));
    const { result } = renderHook(() => useAlertConfig(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useUpdateAlertConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.updateAlertConfig with data", async () => {
    const updated = { slack_webhook_url: "https://hooks.slack.com/new" };
    vi.mocked(api.updateAlertConfig).mockResolvedValue(updated as any);

    const { result } = renderHook(() => useUpdateAlertConfig(), { wrapper: makeWrapper() });
    result.current.mutate({ slack_webhook_url: "https://hooks.slack.com/new" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.updateAlertConfig).toHaveBeenCalledWith({
      slack_webhook_url: "https://hooks.slack.com/new",
    });
  });
});

describe("useDeleteAlertConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.deleteAlertConfig", async () => {
    vi.mocked(api.deleteAlertConfig).mockResolvedValue(undefined as any);

    const { result } = renderHook(() => useDeleteAlertConfig(), { wrapper: makeWrapper() });
    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.deleteAlertConfig).toHaveBeenCalledOnce();
  });
});

describe("useTestAlert", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls api.sendTestAlert with the channel", async () => {
    vi.mocked(api.sendTestAlert).mockResolvedValue({ sent: true } as any);

    const { result } = renderHook(() => useTestAlert(), { wrapper: makeWrapper() });
    result.current.mutate("slack");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.sendTestAlert).toHaveBeenCalledWith("slack");
  });

  it("handles email channel", async () => {
    vi.mocked(api.sendTestAlert).mockResolvedValue({ sent: true } as any);

    const { result } = renderHook(() => useTestAlert(), { wrapper: makeWrapper() });
    result.current.mutate("email");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.sendTestAlert).toHaveBeenCalledWith("email");
  });
});
