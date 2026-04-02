# Dashboard Charts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 4 Recharts visualizations to the dashboard and agent detail pages using data already available from existing hooks.

**Architecture:** Create a shared chart theme config file with severity colors from the CSS theme. Build 4 chart components, then embed them into the existing DashboardPage and AgentDetailPage. All data comes from existing `useIncidents()` and `useEvents()` hooks — no new API endpoints.

**Tech Stack:** Recharts 2.14, React 18, Tailwind CSS, existing TanStack Query hooks

---

### Task 1: Chart theme config

**Files:**
- Create: `dashboard/src/lib/chart-theme.ts`

**Step 1: Create the theme file**

Shared constants for chart colors and styles, pulling from the Tailwind CSS theme:

```typescript
// Severity colors matching --color-severity-* in index.css
export const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ef4444",
  high: "#f97316",
  medium: "#eab308",
  low: "#3b82f6",
};

// Recharts needs explicit light-on-dark styling for dark theme
export const CHART_THEME = {
  background: "transparent",
  text: "#a1a1aa",       // --color-muted-foreground
  grid: "#27272a",       // --color-border
  tooltip: {
    bg: "#18181b",
    border: "#27272a",
    text: "#fafafa",
  },
};
```

**Step 2: Commit**

---

### Task 2: Severity breakdown donut chart (Dashboard page)

**Files:**
- Create: `dashboard/src/components/charts/SeverityBreakdown.tsx`
- Modify: `dashboard/src/pages/DashboardPage.tsx`

**Step 1: Build the donut chart component**

Props: takes `incidents` array from the existing `useIncidents()` hook. Groups by severity, renders a Recharts `PieChart` with `Pie` using `innerRadius` for donut style. Include a centered label showing total count. Custom tooltip showing severity name + count.

**Step 2: Embed in DashboardPage**

Replace the left side of the bottom `lg:grid-cols-2` section. Keep the Agents list card, but add the donut chart as a new card above or beside it. The chart card should have `CardHeader` with title "Severity Breakdown".

**Step 3: Verify visually**

Run: `cd dashboard && npm run dev` — check http://localhost:5173/dashboard
Expected: Donut chart renders with colored segments matching severity colors

**Step 4: Commit**

---

### Task 3: Incident trend area chart (Dashboard page)

**Files:**
- Create: `dashboard/src/components/charts/IncidentTrend.tsx`
- Modify: `dashboard/src/pages/DashboardPage.tsx`

**Step 1: Build the area chart component**

Props: takes `incidents` array. Groups incidents by day (last 7 days), stacks by severity. Uses Recharts `AreaChart` with `Area` components stacked. X-axis shows abbreviated day names. Tooltip shows date + count per severity.

Data transformation:
1. Get last 7 days as date strings
2. For each day, count incidents by severity
3. Output array: `[{ date: "Mon", critical: 2, high: 5, medium: 3, low: 1 }, ...]`

Handle empty days (0 counts) so the chart always shows 7 days.

**Step 2: Embed in DashboardPage**

Add as a full-width card above the two-column agents/incidents section. Give it a `CardHeader` with title "Incident Trend (7 days)".

**Step 3: Verify visually**

**Step 4: Commit**

---

### Task 4: Latency & token sparklines (Agent detail page)

**Files:**
- Create: `dashboard/src/components/charts/Sparkline.tsx`
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`

**Step 1: Build a generic Sparkline component**

Props: `data: number[]`, `color?: string`, `height?: number`. Renders a tiny Recharts `LineChart` with no axes, no grid, no tooltip — just the line. Uses `ResponsiveContainer` for auto-width. Default height 32px.

**Step 2: Add sparklines to the agent detail stats cards**

In AgentDetailPage, the 4 stats cards currently show static values. Add sparklines to the Events and Latency cards:
- Events card: sparkline of `token_count` from recent events
- Latency card: sparkline of `latency_ms` from recent events

Extract the data arrays from `displayEvents` (already available). Place sparkline below the stat value in each card.

**Step 3: Verify visually**

**Step 4: Commit**

---

### Task 5: Detection breakdown bar chart (Agent detail page)

**Files:**
- Create: `dashboard/src/components/charts/DetectorBreakdown.tsx`
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`
- Modify: `dashboard/src/hooks/useIncidents.ts` (add agent filter)

**Step 1: Add agent_id filter to useIncidents hook**

The backend already supports filtering incidents by org, but we need agent-scoped incidents. Update the `useIncidents` hook to accept an optional `agent_id` parameter. Update `api.listIncidents()` to pass it as a query param.

Note: The backend `list_incidents` endpoint may not support `agent_id` filtering yet. Check `backend/app/api/v1/incidents.py` and `backend/app/services/incident_service.py`. If missing, add it.

**Step 2: Build the horizontal bar chart component**

Props: takes `incidents` array scoped to an agent. Extracts all detections from all incidents, groups by detector name, counts occurrences. Renders a Recharts `BarChart` with `layout="vertical"` showing detector name on Y-axis and count on X-axis. Bars colored by avg severity.

**Step 3: Embed in AgentDetailPage**

Add as a new card below the Event Timeline card. Title: "Detection Breakdown". Only render if there are incidents for this agent.

**Step 4: Verify visually**

**Step 5: Run `npm run build` to verify no type errors**

**Step 6: Commit**

---

### Notes

- All charts use data already fetched by existing hooks — no new API endpoints except possibly adding `agent_id` filter to incidents.
- Chart components are in `src/components/charts/` — isolated, reusable.
- Dark theme: Recharts defaults to light theme. The chart theme config ensures all text, grids, and tooltips match the dark background.
- Empty states: All charts should gracefully handle 0 incidents or 0 events — show a "No data yet" message instead of an empty chart.
