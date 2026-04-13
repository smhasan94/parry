import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SidebarProvider, Sidebar, MobileMenuButton, useSidebar } from "@/components/Sidebar";

// Mock @tanstack/react-router hooks used by Sidebar
vi.mock("@tanstack/react-router", () => ({
  useLocation: () => ({ pathname: "/dashboard" }),
  Link: ({ children, to, className, onClick }: { children: React.ReactNode; to: string; className?: string; onClick?: () => void }) => (
    <a href={to} className={className} onClick={onClick}>
      {children}
    </a>
  ),
}));

function renderWithProvider(ui: React.ReactNode) {
  return render(<SidebarProvider>{ui}</SidebarProvider>);
}

describe("Sidebar", () => {
  it("renders the Parry brand name", () => {
    renderWithProvider(<Sidebar />);
    // Multiple "Parry" text nodes may exist (logo + footer version)
    expect(screen.getAllByText(/Parry/)[0]).toBeInTheDocument();
  });

  it("renders navigation links", () => {
    renderWithProvider(<Sidebar />);
    expect(screen.getByText("Overview")).toBeInTheDocument();
    expect(screen.getByText("Agents")).toBeInTheDocument();
    expect(screen.getByText("Incidents")).toBeInTheDocument();
  });

  it("renders all major nav sections", () => {
    renderWithProvider(<Sidebar />);
    expect(screen.getByText("Policies")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("Webhooks")).toBeInTheDocument();
  });

  it("highlights the active route based on location pathname", () => {
    renderWithProvider(<Sidebar />);
    const overviewLink = screen.getByText("Overview").closest("a");
    // /dashboard is the active path, Overview links to /dashboard
    expect(overviewLink?.className).toContain("bg-secondary");
  });

  it("non-active links do not have bg-secondary class", () => {
    renderWithProvider(<Sidebar />);
    const agentsLink = screen.getByText("Agents").closest("a");
    // hover:bg-secondary/50 contains "bg-secondary" as a substring,
    // so match the exact active-link token (space-delimited).
    const classes = agentsLink?.className.split(" ") ?? [];
    expect(classes).not.toContain("bg-secondary");
  });

  it("renders version footer", () => {
    renderWithProvider(<Sidebar />);
    expect(screen.getByText(/Parry v/)).toBeInTheDocument();
  });
});

describe("MobileMenuButton", () => {
  it("renders a button with Toggle navigation label", () => {
    renderWithProvider(<MobileMenuButton />);
    expect(screen.getByLabelText("Toggle navigation")).toBeInTheDocument();
  });

  it("calls toggle when clicked", () => {
    // We test the toggle behavior through context state changes
    function TestHarness() {
      const { open } = useSidebar();
      return (
        <>
          <MobileMenuButton />
          <div data-testid="open-state">{String(open)}</div>
        </>
      );
    }
    renderWithProvider(<TestHarness />);
    expect(screen.getByTestId("open-state").textContent).toBe("false");
    fireEvent.click(screen.getByLabelText("Toggle navigation"));
    expect(screen.getByTestId("open-state").textContent).toBe("true");
  });
});

describe("SidebarProvider context", () => {
  it("provides open, toggle, and close", () => {
    function TestConsumer() {
      const { open, toggle, close } = useSidebar();
      return (
        <>
          <span data-testid="open">{String(open)}</span>
          <button onClick={toggle}>Toggle</button>
          <button onClick={close}>Close</button>
        </>
      );
    }
    renderWithProvider(<TestConsumer />);
    expect(screen.getByTestId("open").textContent).toBe("false");
    fireEvent.click(screen.getByText("Toggle"));
    expect(screen.getByTestId("open").textContent).toBe("true");
    fireEvent.click(screen.getByText("Close"));
    expect(screen.getByTestId("open").textContent).toBe("false");
  });
});
