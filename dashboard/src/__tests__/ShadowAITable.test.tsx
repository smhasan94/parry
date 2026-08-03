import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ShadowAITable } from "@/components/ShadowAITable";
import type { ShadowSystem } from "@/lib/types";

function system(overrides: Partial<ShadowSystem> = {}): ShadowSystem {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    name: "Notion AI",
    provider_name: "Notion",
    risk_level: "limited",
    discovery_source: "sso",
    first_seen_at: "2026-01-05T10:00:00Z",
    last_seen_at: "2026-03-01T10:00:00Z",
    ...overrides,
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
