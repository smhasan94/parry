import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useBlockedEventStream, type LiveStreamMessage } from "@/hooks/useBlockedEventStream";
import { Pause, Play, ShieldOff, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "text-red-300",
  high: "text-orange-300",
  medium: "text-yellow-300",
  low: "text-blue-300",
};

function formatTime(ts: string | undefined): string {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleTimeString();
  } catch {
    return ts;
  }
}

function borderClass(msg: LiveStreamMessage): string {
  if (msg.type === "blocked") return "border-l-red-500";
  if (msg.type === "event") return "border-l-yellow-500";
  return "border-l-transparent";
}

export function BlockedEventFeed() {
  const [paused, setPaused] = useState(false);
  const { messages, connected, clear } = useBlockedEventStream(paused);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-base">
          <div className="flex items-center gap-2">
            <ShieldOff className="h-4 w-4 text-red-400" />
            <span>Live Block Feed</span>
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                connected ? "bg-green-500" : "bg-zinc-500",
              )}
              title={connected ? "Connected" : "Disconnected"}
            />
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPaused((p) => !p)}
            >
              {paused ? (
                <>
                  <Play className="h-3.5 w-3.5" />
                  Resume
                </>
              ) : (
                <>
                  <Pause className="h-3.5 w-3.5" />
                  Pause
                </>
              )}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={clear}
              disabled={messages.length === 0}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {messages.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {connected
              ? "Waiting for live events… blocked calls will appear here in real time."
              : "Connecting to the live event stream…"}
          </p>
        ) : (
          <ul className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
            {messages.map((msg) => (
              <li
                key={msg._id}
                className={cn(
                  "border-l-2 bg-muted/20 px-3 py-2 text-sm",
                  borderClass(msg),
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    {msg.type === "blocked" ? (
                      <span className="rounded bg-red-950/50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-red-300">
                        Blocked
                      </span>
                    ) : (
                      <span className="rounded bg-yellow-950/50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-yellow-300">
                        Detected
                      </span>
                    )}
                    {msg.detector && (
                      <span className="text-xs font-medium text-foreground">
                        {msg.detector}
                      </span>
                    )}
                    {msg.severity && (
                      <span
                        className={cn(
                          "text-xs font-medium uppercase",
                          SEVERITY_STYLES[msg.severity] ?? "text-muted-foreground",
                        )}
                      >
                        {msg.severity}
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {formatTime(msg.ts)}
                  </span>
                </div>
                {msg.reason && (
                  <p className="mt-1 text-xs text-muted-foreground">{msg.reason}</p>
                )}
                {msg.prompt_preview && (
                  <p className="mt-1 truncate text-xs italic text-foreground/80">
                    "{msg.prompt_preview}"
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
