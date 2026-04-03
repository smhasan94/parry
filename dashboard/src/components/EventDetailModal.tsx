import type { AgentEvent } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { X } from "lucide-react";

interface Props {
  event: AgentEvent;
  onClose: () => void;
}

export function EventDetailModal({ event, onClose }: Props) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="mx-4 max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-border bg-card p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Event Detail</h2>
          <Button size="icon" variant="ghost" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="mt-4 space-y-4">
          {/* Metadata */}
          <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
            <span>{new Date(event.timestamp).toLocaleString()}</span>
            {event.model && (
              <span className="rounded bg-secondary px-1.5 py-0.5">{event.model}</span>
            )}
            {event.latency_ms != null && <span>{event.latency_ms}ms</span>}
            {event.token_count != null && <span>{event.token_count} tokens</span>}
          </div>

          {/* Prompt */}
          {event.prompt && (
            <div>
              <h3 className="mb-1 text-xs font-medium uppercase text-muted-foreground">Prompt</h3>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-secondary p-3 text-sm">
                {event.prompt}
              </pre>
            </div>
          )}

          {/* Response */}
          {event.response && (
            <div>
              <h3 className="mb-1 text-xs font-medium uppercase text-muted-foreground">Response</h3>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-secondary p-3 text-sm">
                {event.response}
              </pre>
            </div>
          )}

          {/* Tool Calls */}
          {event.tool_calls && event.tool_calls.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-medium uppercase text-muted-foreground">
                Tool Calls ({event.tool_calls.length})
              </h3>
              <div className="space-y-2">
                {event.tool_calls.map((tc, i) => {
                  const tool = tc as Record<string, unknown>;
                  return (
                    <pre
                      key={i}
                      className="overflow-auto whitespace-pre-wrap rounded-md bg-secondary p-3 text-xs font-mono"
                    >
                      {JSON.stringify(tool, null, 2)}
                    </pre>
                  );
                })}
              </div>
            </div>
          )}

          {/* Event ID */}
          <div className="border-t border-border pt-3">
            <p className="text-xs text-muted-foreground">
              Event ID: <span className="font-mono">{event.id}</span>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
