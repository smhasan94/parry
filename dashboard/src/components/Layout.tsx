import { Outlet } from "@tanstack/react-router";
import { Sidebar } from "./Sidebar";
import { UpgradeModal } from "./UpgradeModal";

export function Layout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
      <UpgradeModal />
    </div>
  );
}
