import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import type { SimulationSample } from "@/lib/api";

interface Props {
  samples: SimulationSample[];
}

/**
 * Expandable list of sample matches from a regression simulation.
 * Highlights the matched span inline so admins can see *why* the
 * pattern fired against this particular event.
 */
export function MatchSampleList({ samples }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (samples.length === 0) {
    return (
      <div className="text-sm text-muted-foreground italic">
        No sample matches to show.
      </div>
    );
  }

  const toggle = (id: string) => {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpanded(next);
  };

  return (
    <ul className="divide-y divide-border rounded-md border">
      {samples.map((sample) => {
        const isOpen = expanded.has(sample.event_id);
        const previewSource =
          sample.matched_field === "prompt"
            ? sample.prompt_preview
            : sample.response_preview;
        return (
          <li key={sample.event_id} className="px-3 py-2">
            <button
              type="button"
              onClick={() => toggle(sample.event_id)}
              className="flex w-full items-start justify-between text-left text-sm"
            >
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{sample.matched_field}</Badge>
                  <span className="font-medium">{sample.agent_name}</span>
                  <span className="text-xs text-muted-foreground">
                    {new Date(sample.timestamp).toLocaleString()}
                  </span>
                </div>
                <div className="mt-1 truncate text-xs text-muted-foreground">
                  {highlight(previewSource, sample.match_span)}
                </div>
              </div>
              <span className="ml-2 text-xs text-muted-foreground">
                {isOpen ? "−" : "+"}
              </span>
            </button>
            {isOpen && (
              <div className="mt-2 space-y-2 rounded bg-muted/50 p-2 text-xs">
                <div>
                  <div className="font-semibold text-muted-foreground">
                    Prompt
                  </div>
                  <div className="whitespace-pre-wrap">
                    {highlight(sample.prompt_preview, sample.match_span)}
                  </div>
                </div>
                {sample.response_preview && (
                  <div>
                    <div className="font-semibold text-muted-foreground">
                      Response
                    </div>
                    <div className="whitespace-pre-wrap">
                      {highlight(sample.response_preview, sample.match_span)}
                    </div>
                  </div>
                )}
                <div className="text-muted-foreground">
                  event id: {sample.event_id}
                </div>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function highlight(text: string, span: string) {
  if (!span || !text) return text;
  const idx = text.toLowerCase().indexOf(span.toLowerCase());
  if (idx < 0) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="rounded bg-yellow-200 px-0.5 dark:bg-yellow-700/60">
        {text.slice(idx, idx + span.length)}
      </mark>
      {text.slice(idx + span.length)}
    </>
  );
}
