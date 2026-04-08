import { useEffect, useRef, useState } from "react";

export interface LiveStreamMessage {
  type: "blocked" | "event" | "keepalive";
  detector?: string;
  reason?: string;
  severity?: "low" | "medium" | "high" | "critical";
  confidence?: number;
  prompt_preview?: string;
  model?: string | null;
  agent_id?: string | null;
  ts?: string;
  // Client-side id so React can key the list even though the backend
  // doesn't assign one to pubsub payloads.
  _id?: string;
}

const MAX_BUFFERED = 50;

/**
 * Subscribes to the org-wide SSE live stream and buffers the last 50
 * non-keepalive messages. Pausing stops mutating the buffer but the
 * underlying EventSource keeps the connection warm so resuming is
 * instant.
 */
export function useBlockedEventStream(paused: boolean) {
  const [messages, setMessages] = useState<LiveStreamMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const pausedRef = useRef(paused);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    const baseUrl = import.meta.env.VITE_API_URL || "";
    const es = new EventSource(`${baseUrl}/api/v1/events/live-stream`);
    esRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (e) => {
      if (pausedRef.current) return;
      try {
        const msg = JSON.parse(e.data) as LiveStreamMessage;
        if (msg.type === "keepalive") return;
        msg._id = `${msg.ts ?? Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        setMessages((prev) => [msg, ...prev].slice(0, MAX_BUFFERED));
      } catch {
        // ignore malformed
      }
    };

    return () => {
      es.close();
      esRef.current = null;
      setConnected(false);
    };
  }, []);

  function clear() {
    setMessages([]);
  }

  return { messages, connected, clear };
}
