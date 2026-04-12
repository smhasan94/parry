import { useState } from "react";
import { Header } from "@/components/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TuningResult } from "@/lib/api";
import { FlaskConical } from "lucide-react";

const DETECTORS = [
  { key: "prompt_injection", label: "Prompt Injection", defaultThreshold: 0.6 },
  { key: "jailbreak", label: "Jailbreak", defaultThreshold: 0.7 },
  { key: "privilege_escalation", label: "Privilege Escalation", defaultThreshold: 0.7 },
  { key: "data_exfiltration", label: "Data Exfiltration", defaultThreshold: 0.5 },
  { key: "tool_misuse", label: "Tool Misuse", defaultThreshold: 0.5 },
];

export function TuningSandboxPage() {
  const [eventsText, setEventsText] = useState("");
  const [thresholds, setThresholds] = useState<Record<string, number>>(
    Object.fromEntries(DETECTORS.map((d) => [d.key, d.defaultThreshold]))
  );
  const [enabled, setEnabled] = useState<Record<string, boolean>>(
    Object.fromEntries(DETECTORS.map((d) => [d.key, true]))
  );

  const mutation = useMutation({
    mutationFn: () => {
      const events = eventsText
        .split("\n")
        .filter((l) => l.trim())
        .map((line) => ({ prompt: line.trim() }));
      const configOverrides: Record<string, Record<string, unknown>> = {};
      for (const d of DETECTORS) {
        configOverrides[d.key] = {
          trigger_threshold: thresholds[d.key],
          enabled: enabled[d.key],
        };
      }
      return api.replayWithTuning(events, configOverrides);
    },
  });

  const result: TuningResult | undefined = mutation.data;

  return (
    <div>
      <Header
        title="Tuning Sandbox"
        description="Replay prompts through detectors with custom thresholds to preview detection behavior."
      />
      <div className="space-y-6 p-6">
        {/* Config */}
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Prompts</CardTitle>
            </CardHeader>
            <CardContent>
              <textarea
                value={eventsText}
                onChange={(e) => setEventsText(e.target.value)}
                placeholder="Enter one prompt per line..."
                className="h-48 w-full resize-none rounded-md border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-primary"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                One prompt per line. Up to 50 prompts.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Detector Thresholds</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {DETECTORS.map((d) => (
                <div key={d.key} className="flex items-center gap-3">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={enabled[d.key]}
                      onChange={(e) =>
                        setEnabled((prev) => ({ ...prev, [d.key]: e.target.checked }))
                      }
                      className="rounded"
                    />
                    <span className="w-36 text-xs">{d.label}</span>
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={thresholds[d.key]}
                    onChange={(e) =>
                      setThresholds((prev) => ({ ...prev, [d.key]: parseFloat(e.target.value) }))
                    }
                    className="flex-1"
                    disabled={!enabled[d.key]}
                  />
                  <span className="w-10 text-right text-xs tabular-nums text-muted-foreground">
                    {(thresholds[d.key] ?? d.defaultThreshold).toFixed(2)}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <Button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || !eventsText.trim()}
        >
          <FlaskConical className="mr-2 h-4 w-4" />
          {mutation.isPending ? "Running..." : "Run Sandbox"}
        </Button>

        {/* Results */}
        {result && (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground">Total Prompts</p>
                  <p className="text-2xl font-bold">{result.total_events}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground">Triggered</p>
                  <p className="text-2xl font-bold text-orange-400">
                    {result.events_with_triggers}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground">Trigger Rate</p>
                  <p className="text-2xl font-bold">{result.trigger_rate}%</p>
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Per-Detector Summary</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {Object.entries(result.detector_summary).map(([name, counts]) => (
                    <div
                      key={name}
                      className="flex items-center justify-between rounded-md border border-border p-3"
                    >
                      <span className="text-xs">{name.replace(/_/g, " ")}</span>
                      <span className="text-xs font-medium">
                        {counts.triggered}/{counts.total}
                      </span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Individual Results</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="divide-y divide-border">
                  {result.results.map((r) => (
                    <div key={r.event_index} className="flex items-center justify-between py-2.5">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-mono">
                          {r.prompt_preview || "(empty)"}
                        </p>
                      </div>
                      <span
                        className={`ml-3 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                          r.any_triggered
                            ? "bg-orange-500/20 text-orange-300"
                            : "bg-emerald-500/20 text-emerald-300"
                        }`}
                      >
                        {r.any_triggered ? "TRIGGERED" : "CLEAN"}
                      </span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
