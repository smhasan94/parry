import { describe, it, expect } from "vitest";
import { SEVERITY_COLORS, SEVERITY_ORDER, CHART_THEME } from "@/lib/chart-theme";

describe("chart theme", () => {
  it("has colors for all severity levels", () => {
    for (const severity of SEVERITY_ORDER) {
      expect(SEVERITY_COLORS[severity]).toBeDefined();
      expect(SEVERITY_COLORS[severity]).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("severity order is critical > high > medium > low", () => {
    expect(SEVERITY_ORDER).toEqual(["critical", "high", "medium", "low"]);
  });

  it("chart theme has dark-mode colors", () => {
    expect(CHART_THEME.text).toBe("#a1a1aa");
    expect(CHART_THEME.grid).toBe("#27272a");
    expect(CHART_THEME.tooltip.bg).toBe("#18181b");
  });
});
