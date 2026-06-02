import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useBlockedEventStream } from "@/hooks/useBlockedEventStream";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: { getToken: vi.fn().mockResolvedValue(null) },
}));

// Mock EventSource
class MockEventSource {
  static OPEN = 1;
  url: string;
  onopen: ((e: Event) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  readyState = MockEventSource.OPEN;

  constructor(url: string) {
    this.url = url;
    // Simulate connection on next tick
    setTimeout(() => {
      this.onopen?.(new Event("open"));
    }, 0);
  }

  close() {
    this.readyState = 2; // CLOSED
  }

  // Helper for tests to simulate incoming messages
  emit(data: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }

  emitRaw(data: string) {
    this.onmessage?.(new MessageEvent("message", { data }));
  }
}

let mockEsInstance: MockEventSource | null = null;

beforeEach(() => {
  mockEsInstance = null;
  vi.stubGlobal("EventSource", class extends MockEventSource {
    constructor(url: string) {
      super(url);
      mockEsInstance = this;
    }
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useBlockedEventStream", () => {
  it("starts with empty messages and disconnected state", () => {
    const { result } = renderHook(() => useBlockedEventStream(false));
    expect(result.current.messages).toEqual([]);
    expect(result.current.connected).toBe(false);
  });

  it("sets connected to true when EventSource opens", async () => {
    const { result } = renderHook(() => useBlockedEventStream(false));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(result.current.connected).toBe(true);
  });

  it("adds message to list when a blocked event arrives", async () => {
    const { result } = renderHook(() => useBlockedEventStream(false));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    act(() => {
      mockEsInstance!.emit({
        type: "blocked",
        detector: "prompt-injection",
        severity: "high",
        reason: "Detected injection",
        ts: "2024-01-01T12:00:00Z",
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]!.type).toBe("blocked");
    expect(result.current.messages[0]!.detector).toBe("prompt-injection");
  });

  it("ignores keepalive messages", async () => {
    const { result } = renderHook(() => useBlockedEventStream(false));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    act(() => {
      mockEsInstance!.emit({ type: "keepalive" });
    });

    expect(result.current.messages).toHaveLength(0);
  });

  it("does not add message when paused", async () => {
    const { result, rerender } = renderHook(
      ({ paused }: { paused: boolean }) => useBlockedEventStream(paused),
      { initialProps: { paused: false } },
    );
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    // Pause the stream
    rerender({ paused: true });

    act(() => {
      mockEsInstance!.emit({ type: "blocked", detector: "test", ts: "2024-01-01T12:00:00Z" });
    });

    expect(result.current.messages).toHaveLength(0);
  });

  it("clears messages when clear() is called", async () => {
    const { result } = renderHook(() => useBlockedEventStream(false));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    act(() => {
      mockEsInstance!.emit({ type: "blocked", ts: "2024-01-01T12:00:00Z" });
    });
    expect(result.current.messages).toHaveLength(1);

    act(() => {
      result.current.clear();
    });
    expect(result.current.messages).toHaveLength(0);
  });

  it("ignores malformed JSON messages", async () => {
    const { result } = renderHook(() => useBlockedEventStream(false));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    act(() => {
      mockEsInstance!.emitRaw("not valid json{{{{");
    });

    expect(result.current.messages).toHaveLength(0);
  });

  it("sets connected to false when onerror fires", async () => {
    const { result } = renderHook(() => useBlockedEventStream(false));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(result.current.connected).toBe(true);

    act(() => {
      mockEsInstance!.onerror?.(new Event("error"));
    });
    expect(result.current.connected).toBe(false);
  });

  it("assigns a unique _id to each message", async () => {
    const { result } = renderHook(() => useBlockedEventStream(false));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    act(() => {
      mockEsInstance!.emit({ type: "blocked", ts: "2024-01-01T12:00:00Z" });
      mockEsInstance!.emit({ type: "event", ts: "2024-01-01T12:00:01Z" });
    });

    const ids = result.current.messages.map((m) => m._id);
    expect(ids[0]).not.toBe(ids[1]);
    expect(ids[0]).toBeDefined();
  });
});
