import { useEffect, useRef, useState } from "react";
import type { AgentEvent } from "@/lib/types";

export function useAgentEventStream(agentId: string | null) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!agentId) return;

    const baseUrl = import.meta.env.VITE_API_URL || "";
    const url = `${baseUrl}/api/v1/events/stream?agent_id=${agentId}`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => setConnected(true);

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as AgentEvent;
        setEvents((prev) => [event, ...prev].slice(0, 100));
      } catch {
        // ignore malformed events
      }
    };

    es.onerror = () => {
      setConnected(false);
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
      setConnected(false);
    };
  }, [agentId]);

  return { events, connected };
}
