import { useLocation, Link } from "@tanstack/react-router";
import {
  Shield,
  LayoutDashboard,
  Bot,
  AlertTriangle,
  FileCheck,
  FileCode,
  FileDown,
  Settings,
  Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/incidents", label: "Incidents", icon: AlertTriangle },
  { to: "/policies", label: "Policies", icon: FileCheck },
  { to: "/custom-rules", label: "Custom Rules", icon: FileCode },
  { to: "/reports", label: "Reports", icon: FileDown },
  { to: "/audit-log", label: "Audit Log", icon: Activity },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

export function Sidebar() {
  const location = useLocation();

  return (
    <aside className="flex h-screen w-64 flex-col border-r border-border bg-background">
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-border px-6">
        <Shield className="h-6 w-6 text-primary" />
        <span className="text-lg font-bold tracking-tight">Parry</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navItems.map((item) => {
          const active = location.pathname.startsWith(item.to);
          return (
            <Link
              key={item.to}
              to={item.to}
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
  );
}
