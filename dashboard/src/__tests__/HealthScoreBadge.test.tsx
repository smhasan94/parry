import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HealthScoreBadge } from "@/components/HealthScoreBadge";

describe("HealthScoreBadge", () => {
  it("renders the score as text", () => {
    render(<HealthScoreBadge score={85} />);
    expect(screen.getByText("85")).toBeInTheDocument();
  });

  it("renders dash for null score", () => {
    render(<HealthScoreBadge score={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders grade when provided", () => {
    render(<HealthScoreBadge score={92} grade="A" />);
    expect(screen.getByText("A")).toBeInTheDocument();
  });

  it("does not render grade element when grade is omitted", () => {
    render(<HealthScoreBadge score={80} />);
    expect(screen.queryByText("A")).not.toBeInTheDocument();
  });

  it("has correct title for a valid score with grade", () => {
    render(<HealthScoreBadge score={95} grade="A+" />);
    const badge = screen.getByTitle("Health 95 (A+)");
    expect(badge).toBeInTheDocument();
  });

  it("has correct title for null score", () => {
    render(<HealthScoreBadge score={null} />);
    const badge = screen.getByTitle("Health score not yet computed");
    expect(badge).toBeInTheDocument();
  });

  it("has correct title for score without grade", () => {
    render(<HealthScoreBadge score={72} />);
    const badge = screen.getByTitle("Health 72");
    expect(badge).toBeInTheDocument();
  });

  it("applies green classes for score >= 90", () => {
    const { container } = render(<HealthScoreBadge score={90} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("green");
  });

  it("applies red classes for score < 40", () => {
    const { container } = render(<HealthScoreBadge score={20} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("red");
  });

  it("applies orange classes for score in 40-59 range", () => {
    const { container } = render(<HealthScoreBadge score={50} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("orange");
  });

  it("applies yellow classes for score in 60-74 range", () => {
    const { container } = render(<HealthScoreBadge score={65} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("yellow");
  });

  it("applies blue classes for score in 75-89 range", () => {
    const { container } = render(<HealthScoreBadge score={80} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("blue");
  });
});
