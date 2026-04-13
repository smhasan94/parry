import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { BlockedEventFeed } from "@/components/BlockedEventFeed";
import type { LiveStreamMessage } from "@/hooks/useBlockedEventStream";

// Mock the hook so we can control the stream state
vi.mock("@/hooks/useBlockedEventStream", () => ({
  useBlockedEventStream: vi.fn(),
}));

import { useBlockedEventStream } from "@/hooks/useBlockedEventStream";

const mockClear = vi.fn();

function setupMock(
  overrides: Partial<{ messages: LiveStreamMessage[]; connected: boolean }> = {},
) {
  vi.mocked(useBlockedEventStream).mockReturnValue({
    messages: overrides.messages ?? [],
    connected: overrides.connected ?? false,
    clear: mockClear,
  });
}

describe("BlockedEventFeed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows connecting message when not connected and no messages", () => {
    setupMock({ connected: false, messages: [] });
    render(<BlockedEventFeed />);
    expect(screen.getByText(/Connecting to the live event stream/)).toBeInTheDocument();
  });

  it("shows waiting message when connected but no messages", () => {
    setupMock({ connected: true, messages: [] });
    render(<BlockedEventFeed />);
    expect(screen.getByText(/Waiting for live events/)).toBeInTheDocument();
  });

  it("shows connected indicator when connected", () => {
    setupMock({ connected: true });
    const { container } = render(<BlockedEventFeed />);
    const dot = container.querySelector('[title="Connected"]');
    expect(dot).toBeInTheDocument();
  });

  it("shows disconnected indicator when not connected", () => {
    setupMock({ connected: false });
    const { container } = render(<BlockedEventFeed />);
    const dot = container.querySelector('[title="Disconnected"]');
    expect(dot).toBeInTheDocument();
  });

  it("renders message list when messages are present", () => {
    const messages: LiveStreamMessage[] = [
      {
        _id: "m1",
        type: "blocked",
        detector: "prompt-injection",
        severity: "critical",
        reason: "Suspicious pattern detected",
        ts: "2024-01-01T12:00:00Z",
      },
    ];
    setupMock({ messages, connected: true });
    render(<BlockedEventFeed />);

    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.getByText("prompt-injection")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getByText("Suspicious pattern detected")).toBeInTheDocument();
  });

  it("renders 'Detected' badge for event type messages", () => {
    const messages: LiveStreamMessage[] = [
      {
        _id: "m2",
        type: "event",
        detector: "anomaly",
        severity: "medium",
        ts: "2024-01-01T12:00:00Z",
      },
    ];
    setupMock({ messages, connected: true });
    render(<BlockedEventFeed />);
    expect(screen.getByText("Detected")).toBeInTheDocument();
  });

  it("shows prompt preview when present", () => {
    const messages: LiveStreamMessage[] = [
      {
        _id: "m3",
        type: "blocked",
        prompt_preview: "Ignore previous instructions",
        ts: "2024-01-01T12:00:00Z",
      },
    ];
    setupMock({ messages, connected: true });
    render(<BlockedEventFeed />);
    expect(screen.getByText(/"Ignore previous instructions"/)).toBeInTheDocument();
  });

  it("renders Pause button when not paused", () => {
    setupMock({ connected: true });
    render(<BlockedEventFeed />);
    expect(screen.getByText("Pause")).toBeInTheDocument();
  });

  it("toggles to Resume when Pause is clicked", () => {
    setupMock({ connected: true });
    render(<BlockedEventFeed />);
    fireEvent.click(screen.getByText("Pause"));
    expect(screen.getByText("Resume")).toBeInTheDocument();
  });

  it("calls clear when the trash button is clicked", () => {
    const messages: LiveStreamMessage[] = [
      { _id: "m4", type: "blocked", ts: "2024-01-01T12:00:00Z" },
    ];
    setupMock({ messages, connected: true });
    render(<BlockedEventFeed />);
    // Trash button is only enabled when there are messages
    // Find by lucide icon container - get all buttons and click the ghost one
    const buttons = screen.getAllByRole("button");
    // The trash button is the last button (after Pause)
    fireEvent.click(buttons[buttons.length - 1]);
    expect(mockClear).toHaveBeenCalledOnce();
  });

  it("renders multiple messages", () => {
    const messages: LiveStreamMessage[] = [
      { _id: "m5", type: "blocked", detector: "detector-A", ts: "2024-01-01T12:00:00Z" },
      { _id: "m6", type: "event", detector: "detector-B", ts: "2024-01-01T12:01:00Z" },
    ];
    setupMock({ messages, connected: true });
    render(<BlockedEventFeed />);

    expect(screen.getByText("detector-A")).toBeInTheDocument();
    expect(screen.getByText("detector-B")).toBeInTheDocument();
  });
});
