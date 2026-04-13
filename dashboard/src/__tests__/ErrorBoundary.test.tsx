import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBoundary } from "@/components/ErrorBoundary";

// Suppress console.error noise from intentional throws in tests
beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

function BrokenComponent({ message }: { message?: string }): never {
  throw new Error(message ?? "Test error");
}

function GoodComponent() {
  return <div>All good</div>;
}

describe("ErrorBoundary", () => {
  it("renders children when no error is thrown", () => {
    render(
      <ErrorBoundary>
        <GoodComponent />
      </ErrorBoundary>,
    );
    expect(screen.getByText("All good")).toBeInTheDocument();
  });

  it("renders fallback UI when child throws", () => {
    render(
      <ErrorBoundary>
        <BrokenComponent />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  it("shows the error message from the thrown error", () => {
    render(
      <ErrorBoundary>
        <BrokenComponent message="My custom error message" />
      </ErrorBoundary>,
    );
    expect(screen.getByText("My custom error message")).toBeInTheDocument();
  });

  it("renders a Reload Page button in the fallback", () => {
    render(
      <ErrorBoundary>
        <BrokenComponent />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("button", { name: /reload page/i })).toBeInTheDocument();
  });

  it("does not render children in the fallback state", () => {
    render(
      <ErrorBoundary>
        <BrokenComponent />
      </ErrorBoundary>,
    );
    // The broken component's own output (none) and the children wrapper
    // should not show "All good" - but we test the fallback is showing instead
    expect(screen.queryByText("All good")).not.toBeInTheDocument();
  });
});
