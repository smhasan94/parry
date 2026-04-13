import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { OrgCostSummaryCard } from "@/components/OrgCostSummaryCard";
import type { ReactNode } from "react";

vi.mock("@/lib/api", () => ({
  api: {
    getOrgSpendSummary: vi.fn(),
  },
}));

import { api } from "@/lib/api";

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false },
    },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const baseData = {
  hour_spend: 0.05,
  day_spend: 1.23,
  month_spend: 42.0,
  top_agents: [
    { agent_id: "a-1", agent_name: "support-bot", month_spend: 30.0 },
    { agent_id: "a-2", agent_name: "sales-bot", month_spend: 12.0 },
  ],
  total_budget_cap: null,
};

describe("OrgCostSummaryCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", () => {
    vi.mocked(api.getOrgSpendSummary).mockReturnValue(new Promise(() => {}));
    render(<OrgCostSummaryCard />, { wrapper: makeWrapper() });
    expect(screen.getByText(/Loading spend data/i)).toBeInTheDocument();
  });

  it("renders period spend values after load", async () => {
    vi.mocked(api.getOrgSpendSummary).mockResolvedValue(baseData as any);
    render(<OrgCostSummaryCard />, { wrapper: makeWrapper() });

    await waitFor(() => expect(screen.getByText("$0.05")).toBeInTheDocument());
    expect(screen.getByText("$1.23")).toBeInTheDocument();
    expect(screen.getByText("$42.00")).toBeInTheDocument();
    expect(screen.getByText("Last hour")).toBeInTheDocument();
    expect(screen.getByText("Last 24 h")).toBeInTheDocument();
    expect(screen.getByText("Last 30 d")).toBeInTheDocument();
  });

  it("renders top agents list", async () => {
    vi.mocked(api.getOrgSpendSummary).mockResolvedValue(baseData as any);
    render(<OrgCostSummaryCard />, { wrapper: makeWrapper() });

    await waitFor(() => expect(screen.getByText("support-bot")).toBeInTheDocument());
    expect(screen.getByText("sales-bot")).toBeInTheDocument();
    expect(screen.getByText("$30.00")).toBeInTheDocument();
    expect(screen.getByText("$12.00")).toBeInTheDocument();
  });

  it("shows empty state when no agents have spend", async () => {
    vi.mocked(api.getOrgSpendSummary).mockResolvedValue({
      ...baseData,
      top_agents: [],
      hour_spend: 0,
      day_spend: 0,
      month_spend: 0,
    } as any);
    render(<OrgCostSummaryCard />, { wrapper: makeWrapper() });

    await waitFor(() =>
      expect(screen.getByText(/No spend recorded/i)).toBeInTheDocument(),
    );
  });

  it("shows budget utilisation bar when cap is set", async () => {
    vi.mocked(api.getOrgSpendSummary).mockResolvedValue({
      ...baseData,
      total_budget_cap: 100.0,
    } as any);
    render(<OrgCostSummaryCard />, { wrapper: makeWrapper() });

    await waitFor(() =>
      expect(screen.getByText("Monthly budget")).toBeInTheDocument(),
    );
    // Shows spent / cap
    expect(screen.getByText("$42.00 / $100.00")).toBeInTheDocument();
  });

  it("hides budget bar when no cap configured", async () => {
    vi.mocked(api.getOrgSpendSummary).mockResolvedValue(baseData as any);
    render(<OrgCostSummaryCard />, { wrapper: makeWrapper() });

    await waitFor(() => expect(screen.getByText("$42.00")).toBeInTheDocument());
    expect(screen.queryByText("Monthly budget")).not.toBeInTheDocument();
  });
});
