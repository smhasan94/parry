import { describe, it, expect, beforeEach } from "vitest";
import { useUIStore } from "@/lib/store";

describe("useUIStore", () => {
  beforeEach(() => {
    useUIStore.setState({ sidebarOpen: true });
  });

  it("defaults to sidebar open", () => {
    expect(useUIStore.getState().sidebarOpen).toBe(true);
  });

  it("toggleSidebar flips state", () => {
    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().sidebarOpen).toBe(false);

    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().sidebarOpen).toBe(true);
  });

  it("setSidebarOpen sets explicit value", () => {
    useUIStore.getState().setSidebarOpen(false);
    expect(useUIStore.getState().sidebarOpen).toBe(false);

    useUIStore.getState().setSidebarOpen(true);
    expect(useUIStore.getState().sidebarOpen).toBe(true);
  });

  it("setSidebarOpen(false) then toggle opens it", () => {
    useUIStore.getState().setSidebarOpen(false);
    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().sidebarOpen).toBe(true);
  });
});
