import type { Severity } from "./types";

export const SEVERITY_COLORS: Record<Severity, string> = {
  critical: "#ef4444",
  high: "#f97316",
  medium: "#eab308",
  low: "#3b82f6",
};

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low"];

export const CHART_THEME = {
  text: "#a1a1aa",
  grid: "#27272a",
  tooltip: {
    bg: "#18181b",
    border: "#27272a",
    text: "#fafafa",
  },
} as const;
