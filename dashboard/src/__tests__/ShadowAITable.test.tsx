import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ShadowAITable } from "@/components/ShadowAITable";
import type { ShadowSystem } from "@/lib/types";

function system(overrides: Partial<ShadowSystem> = {}): ShadowSystem {
  const base = {
    id: "11111111-1111-1111-1111-111111111111",
    name: "Notion AI",
    provider_name: "Notion",
    risk_level: "limited",
    proposed_risk_level: null,
    proposed_reasoning: null,
    is_proposed: false,
    pending_classification_id: null,
    discovery_source: "sso",
    first_seen_at: "2026-01-05T10:00:00Z",
    last_seen_at: "2026-03-01T10:00:00Z",
    ...overrides,
  };
  // Mirrors the backend: approved tier wins, else the proposal.
  return {
    ...base,
    effective_risk_level:
      overrides.effective_risk_level ??
      (base.risk_level !== "unclassified"
        ? base.risk_level
        : (base.proposed_risk_level ?? "unclassified")),
  };
}

describe("ShadowAITable", () => {
  it("renders a row per discovered system", () => {
    render(
      <ShadowAITable
        systems={[system(), system({ id: "2", name: "Jasper", provider_name: "Jasper AI Inc" })]}
      />,
    );

    expect(screen.getByText("Notion AI")).toBeInTheDocument();
    expect(screen.getByText("Jasper")).toBeInTheDocument();
  });

  it("shows the vendor alongside the service name", () => {
    render(<ShadowAITable systems={[system({ provider_name: "Notion Labs" })]} />);

    expect(screen.getByText("Notion Labs")).toBeInTheDocument();
  });

  it("labels an unclassified system rather than leaving the tier blank", () => {
    render(<ShadowAITable systems={[system({ risk_level: "unclassified" })]} />);

    expect(screen.getByText("Unclassified")).toBeInTheDocument();
  });

  it("renders an empty state when nothing was discovered", () => {
    render(<ShadowAITable systems={[]} />);

    expect(screen.getByText(/no shadow ai/i)).toBeInTheDocument();
  });

  it("falls back to a dash when the vendor is unknown", () => {
    render(<ShadowAITable systems={[system({ provider_name: null })]} />);

    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("marks high risk systems so they read as urgent", () => {
    render(<ShadowAITable systems={[system({ risk_level: "high" })]} />);

    expect(screen.getByText("High")).toHaveAttribute("data-risk", "high");
  });

  it("shows when a system was last seen", () => {
    render(<ShadowAITable systems={[system({ last_seen_at: "2026-03-01T10:00:00Z" })]} />);

    expect(screen.getByTitle("Last seen 2026-03-01T10:00:00Z")).toBeInTheDocument();
  });

  it("handles a system that has never been seen", () => {
    render(<ShadowAITable systems={[system({ last_seen_at: null })]} />);

    expect(screen.getByTitle("Never seen")).toBeInTheDocument();
  });
});

describe("ShadowAITable proposed tiers", () => {
  function proposed(overrides: Partial<ShadowSystem> = {}): ShadowSystem {
    return {
      ...system(),
      risk_level: "unclassified",
      proposed_risk_level: "high",
      proposed_reasoning: "Screens job applicants — Annex III employment.",
      effective_risk_level: "high",
      is_proposed: true,
      ...overrides,
    };
  }

  it("renders the proposed tier rather than the unreviewed placeholder", () => {
    render(<ShadowAITable systems={[proposed()]} />);

    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.queryByText("Unclassified")).not.toBeInTheDocument();
  });

  it("marks a proposed tier as awaiting review", () => {
    render(<ShadowAITable systems={[proposed()]} />);

    // Never present a catalog guess as an approved classification.
    expect(screen.getByText(/pending review/i)).toBeInTheDocument();
  });

  it("does not mark an approved tier as pending", () => {
    render(
      <ShadowAITable
        systems={[
          proposed({ risk_level: "limited", effective_risk_level: "limited", is_proposed: false }),
        ]}
      />,
    );

    expect(screen.queryByText(/pending review/i)).not.toBeInTheDocument();
  });

  it("exposes the reasoning so a reviewer can see why", () => {
    render(<ShadowAITable systems={[proposed()]} />);

    expect(screen.getByTitle(/Annex III employment/)).toBeInTheDocument();
  });

  it("still renders a system with nothing proposed", () => {
    render(
      <ShadowAITable
        systems={[
          proposed({
            proposed_risk_level: null,
            proposed_reasoning: null,
            effective_risk_level: "unclassified",
            is_proposed: false,
          }),
        ]}
      />,
    );

    expect(screen.getByText("Unclassified")).toBeInTheDocument();
  });
});

describe("ShadowAITable review actions", () => {
  function reviewable(overrides: Partial<ShadowSystem> = {}): ShadowSystem {
    return {
      ...system(),
      risk_level: "unclassified",
      proposed_risk_level: "high",
      proposed_reasoning: "Annex III employment screening.",
      effective_risk_level: "high",
      is_proposed: true,
      pending_classification_id: "aaaaaaaa-0000-0000-0000-000000000001",
      ...overrides,
    };
  }

  it("offers approve and reject on a pending proposal", () => {
    render(<ShadowAITable systems={[reviewable()]} onApprove={vi.fn()} onReject={vi.fn()} />);

    expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
  });

  it("approves with the classification id, not the system id", () => {
    const onApprove = vi.fn();
    render(<ShadowAITable systems={[reviewable()]} onApprove={onApprove} onReject={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /approve/i }));

    expect(onApprove).toHaveBeenCalledWith("aaaaaaaa-0000-0000-0000-000000000001");
  });

  it("rejects with the classification id", () => {
    const onReject = vi.fn();
    render(<ShadowAITable systems={[reviewable()]} onApprove={vi.fn()} onReject={onReject} />);

    fireEvent.click(screen.getByRole("button", { name: /reject/i }));

    expect(onReject).toHaveBeenCalledWith("aaaaaaaa-0000-0000-0000-000000000001");
  });

  it("offers no review actions once a tier is approved", () => {
    render(
      <ShadowAITable
        systems={[
          reviewable({
            risk_level: "high",
            effective_risk_level: "high",
            is_proposed: false,
            pending_classification_id: null,
          }),
        ]}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });

  it("renders read-only when no handlers are supplied", () => {
    render(<ShadowAITable systems={[reviewable()]} />);

    // A viewer without approve rights still sees the finding.
    expect(screen.getByText("Notion AI")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });
});
