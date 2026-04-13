import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ModelSpendBreakdown } from "@/components/ModelSpendBreakdown";

const sampleData = [
  { model: "gpt-4o", count: 120, spend_usd: 5.25 },
  { model: "claude-3-5-sonnet", count: 80, spend_usd: 2.10 },
  { model: "gpt-3.5-turbo", count: 50, spend_usd: 0.50 },
];

describe("ModelSpendBreakdown", () => {
  it("renders empty state when no data", () => {
    render(<ModelSpendBreakdown data={[]} />);
    expect(screen.getByText("No model spend data yet.")).toBeInTheDocument();
  });

  it("renders empty state when data is undefined-like empty array", () => {
    render(<ModelSpendBreakdown data={[]} />);
    const emptyMsg = screen.getByText(/No model spend data yet/);
    expect(emptyMsg).toBeInTheDocument();
  });

  it("renders all model names", () => {
    render(<ModelSpendBreakdown data={sampleData} />);
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("claude-3-5-sonnet")).toBeInTheDocument();
    expect(screen.getByText("gpt-3.5-turbo")).toBeInTheDocument();
  });

  it("renders spend values formatted with dollar sign", () => {
    render(<ModelSpendBreakdown data={sampleData} />);
    expect(screen.getByText("$5.25")).toBeInTheDocument();
    expect(screen.getByText("$2.10")).toBeInTheDocument();
    expect(screen.getByText("$0.50")).toBeInTheDocument();
  });

  it("renders call counts", () => {
    render(<ModelSpendBreakdown data={sampleData} />);
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("80")).toBeInTheDocument();
    expect(screen.getByText("50")).toBeInTheDocument();
  });

  it("renders a list item for each model", () => {
    const { container } = render(<ModelSpendBreakdown data={sampleData} />);
    const items = container.querySelectorAll("li");
    expect(items).toHaveLength(3);
  });

  it("renders single model correctly", () => {
    render(<ModelSpendBreakdown data={[{ model: "gpt-4", count: 5, spend_usd: 1.00 }]} />);
    expect(screen.getByText("gpt-4")).toBeInTheDocument();
    expect(screen.getByText("$1.00")).toBeInTheDocument();
  });
});
