import { cn } from "@/lib/utils";

/**
 * Coloured pill showing an agent's 0–100 health score.
 *
 * Colour bands mirror the dashboard UI spec:
 *   90+ green, 75+ blue, 60+ yellow, 40+ orange, else red.
 * ``null`` scores render as a muted "—" badge so the layout doesn't
 * shift while the cache is cold.
 */

interface HealthScoreBadgeProps {
  score: number | null;
  grade?: string | null;
  size?: "sm" | "md";
}

function bandClasses(score: number | null): string {
  if (score === null) return "bg-muted/40 text-muted-foreground border-muted";
  if (score >= 90) return "bg-green-950/50 text-green-300 border-green-900";
  if (score >= 75) return "bg-blue-950/50 text-blue-300 border-blue-900";
  if (score >= 60) return "bg-yellow-950/50 text-yellow-300 border-yellow-900";
  if (score >= 40) return "bg-orange-950/50 text-orange-300 border-orange-900";
  return "bg-red-950/50 text-red-300 border-red-900";
}

export function HealthScoreBadge({
  score,
  grade,
  size = "sm",
}: HealthScoreBadgeProps) {
  const label = score === null ? "—" : String(score);
  const classes = bandClasses(score);
  const sizing =
    size === "sm"
      ? "px-2 py-0.5 text-xs"
      : "px-2.5 py-1 text-sm";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border font-medium",
        sizing,
        classes,
      )}
      title={
        score === null
          ? "Health score not yet computed"
          : `Health ${label}${grade ? ` (${grade})` : ""}`
      }
    >
      <span className="font-semibold tabular-nums">{label}</span>
      {grade && <span className="opacity-70">{grade}</span>}
    </span>
  );
}
