import { useLocation, Link } from "@tanstack/react-router";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  Cpu,
  FileCheck,
  FileCode,
  FileDown,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  Menu,
  Plug,
  Radar,
  Radio,
  Scale,
  Settings,
  Shield,
  Store,
  Swords,
  Users,
  Webhook,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

// Sidebar open/close state shared between Layout and Sidebar
interface SidebarContextValue {
  open: boolean;
  toggle: () => void;
  close: () => void;
}

const SidebarContext = createContext<SidebarContextValue>({
  open: false,
  toggle: () => {},
  close: () => {},
});

export function SidebarProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const toggle = useCallback(() => setOpen((v) => !v), []);
  const close = useCallback(() => setOpen(false), []);
  return (
    <SidebarContext.Provider value={{ open, toggle, close }}>
      {children}
    </SidebarContext.Provider>
  );
}

export function useSidebar() {
  return useContext(SidebarContext);
}

export function MobileMenuButton() {
  const { toggle } = useSidebar();
  return (
    <button
      onClick={toggle}
      className="inline-flex items-center justify-center rounded-md p-2 text-muted-foreground hover:bg-secondary hover:text-foreground lg:hidden"
      aria-label="Toggle navigation"
    >
      <Menu className="h-5 w-5" />
    </button>
  );
}

const navItems = [
  { to: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/fleet", label: "Fleet Overview", icon: BarChart3 },
  { to: "/agent-groups", label: "Agent Groups", icon: Users },
  { to: "/sdk-health", label: "SDK Health", icon: Cpu },
  { to: "/incidents", label: "Incidents", icon: AlertTriangle },
  { to: "/policies", label: "Policies", icon: FileCheck },
  { to: "/custom-rules", label: "Custom Rules", icon: FileCode },
  { to: "/community-rules", label: "Community Rules", icon: Store },
  { to: "/tuning", label: "Tuning Sandbox", icon: FlaskConical },
  { to: "/reports", label: "Reports", icon: FileDown },
  { to: "/audit-log", label: "Audit Log", icon: Activity },
  { to: "/slo", label: "SLOs", icon: Gauge },
  { to: "/red-team", label: "Red Team", icon: Swords },
  { to: "/mcp", label: "MCP Servers", icon: Plug },
  { to: "/threat-intel", label: "Threat Intel", icon: Radio },
  { to: "/webhooks", label: "Webhooks", icon: Webhook },
  { to: "/shadow-ai", label: "Shadow AI", icon: Radar },
  { to: "/compliance", label: "AI Act Compliance", icon: Scale },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

export function Sidebar() {
  const location = useLocation();
  const { open, close } = useSidebar();

  return (
    <>
      {/* Mobile backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={close}
          aria-hidden="true"
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-border bg-background transition-transform duration-200 lg:static lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {/* Logo */}
        <div className="flex h-14 items-center justify-between border-b border-border px-6">
          <div className="flex items-center gap-2">
            <Shield className="h-6 w-6 text-primary" />
            <span className="text-lg font-bold tracking-tight">Parry</span>
          </div>
          <button
            onClick={close}
            className="rounded-md p-1 text-muted-foreground hover:text-foreground lg:hidden"
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          {navItems.map((item) => {
            const active = location.pathname.startsWith(item.to);
            return (
              <Link
                key={item.to}
                to={item.to}
                onClick={close}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                )}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="border-t border-border p-4">
          <p className="text-xs text-muted-foreground">Parry v0.1.0</p>
        </div>
      </aside>
    </>
  );
}
