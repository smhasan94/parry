import { createRouter, createRoute, createRootRoute, redirect } from "@tanstack/react-router";
import { Layout } from "@/components/Layout";
import { DashboardPage } from "@/pages/DashboardPage";
import { AgentsPage } from "@/pages/AgentsPage";
import { AgentDetailPage } from "@/pages/AgentDetailPage";
import { IncidentsPage } from "@/pages/IncidentsPage";
import { PoliciesPage } from "@/pages/PoliciesPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { OnboardingPage } from "@/pages/OnboardingPage";
import { AuditLogPage } from "@/pages/AuditLogPage";
import { CustomRulesPage } from "@/pages/CustomRulesPage";
import { ReportsPage } from "@/pages/ReportsPage";

const rootRoute = createRootRoute({
  component: Layout,
  notFoundComponent: NotFoundPage,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: "/dashboard" });
  },
});

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/dashboard",
  component: DashboardPage,
});

const agentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/agents",
  component: AgentsPage,
});

const agentDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/agents/$agentId",
  component: AgentDetailPage,
});

const incidentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/incidents",
  component: IncidentsPage,
});

const policiesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/policies",
  component: PoliciesPage,
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: SettingsPage,
});

const setupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/setup",
  component: OnboardingPage,
});

const auditRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/audit-log",
  component: AuditLogPage,
});

const customRulesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/custom-rules",
  component: CustomRulesPage,
});

const reportsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/reports",
  component: ReportsPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  dashboardRoute,
  agentsRoute,
  agentDetailRoute,
  incidentsRoute,
  policiesRoute,
  customRulesRoute,
  reportsRoute,
  settingsRoute,
  setupRoute,
  auditRoute,
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
