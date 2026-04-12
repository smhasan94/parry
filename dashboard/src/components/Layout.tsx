import { Outlet } from "@tanstack/react-router";
import { Sidebar, SidebarProvider, MobileMenuButton } from "./Sidebar";
import { UpgradeModal } from "./UpgradeModal";

export function Layout() {
  return (
    <SidebarProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Mobile header — visible only on small screens */}
          <div className="flex h-14 items-center gap-2 border-b border-border px-4 lg:hidden">
            <MobileMenuButton />
            <span className="text-sm font-bold">Parry</span>
          </div>
          <main className="flex-1 overflow-y-auto">
            <Outlet />
          </main>
        </div>
        <UpgradeModal />
      </div>
    </SidebarProvider>
  );
}
