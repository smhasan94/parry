import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { UpgradeModal } from "@/components/UpgradeModal";

// Mock the api module so we don't hit real endpoints
vi.mock("@/lib/api", () => ({
  api: {
    createCheckoutSession: vi.fn(),
  },
}));

function dispatchUpgradeEvent(message?: string) {
  act(() => {
    window.dispatchEvent(
      new CustomEvent("parry:upgrade-required", {
        detail: { message },
      }),
    );
  });
}

describe("UpgradeModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing by default (closed)", () => {
    render(<UpgradeModal />);
    expect(screen.queryByText("Upgrade Required")).not.toBeInTheDocument();
  });

  it("opens when parry:upgrade-required event fires", () => {
    render(<UpgradeModal />);
    dispatchUpgradeEvent("You've hit your limit.");
    expect(screen.getByText("Upgrade Required")).toBeInTheDocument();
  });

  it("displays the message from the event detail", () => {
    render(<UpgradeModal />);
    dispatchUpgradeEvent("Your plan limit has been reached.");
    expect(screen.getByText("Your plan limit has been reached.")).toBeInTheDocument();
  });

  it("uses fallback message when event detail has no message", () => {
    render(<UpgradeModal />);
    dispatchUpgradeEvent(undefined);
    expect(screen.getByText("You've reached your plan limit.")).toBeInTheDocument();
  });

  it("closes when Maybe later button is clicked", () => {
    render(<UpgradeModal />);
    dispatchUpgradeEvent("Limit reached");
    expect(screen.getByText("Upgrade Required")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Maybe later"));
    expect(screen.queryByText("Upgrade Required")).not.toBeInTheDocument();
  });

  it("closes when Maybe later is clicked", () => {
    render(<UpgradeModal />);
    dispatchUpgradeEvent("Limit");
    fireEvent.click(screen.getByText("Maybe later"));
    expect(screen.queryByText("Upgrade Required")).not.toBeInTheDocument();
  });

  it("renders Upgrade button when open", () => {
    render(<UpgradeModal />);
    dispatchUpgradeEvent();
    expect(screen.getByRole("button", { name: /upgrade/i })).toBeInTheDocument();
  });

  it("listens to multiple events and shows latest message", () => {
    render(<UpgradeModal />);
    dispatchUpgradeEvent("First message");
    fireEvent.click(screen.getByText("Maybe later"));
    dispatchUpgradeEvent("Second message");
    expect(screen.getByText("Second message")).toBeInTheDocument();
  });
});
