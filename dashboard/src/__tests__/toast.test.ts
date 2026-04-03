import { describe, it, expect, vi, beforeEach } from "vitest";
import { useToastStore, toast } from "@/components/ui/toast";

describe("toast store", () => {
  beforeEach(() => {
    useToastStore.setState({ toasts: [] });
  });

  it("adds a toast", () => {
    toast("Something went wrong");
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].message).toBe("Something went wrong");
    expect(toasts[0].type).toBe("error");
  });

  it("adds a success toast", () => {
    toast("Created successfully", "success");
    const toasts = useToastStore.getState().toasts;
    expect(toasts[0].type).toBe("success");
  });

  it("removes a toast by id", () => {
    toast("First");
    toast("Second");
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(2);

    useToastStore.getState().remove(toasts[0].id);
    expect(useToastStore.getState().toasts).toHaveLength(1);
    expect(useToastStore.getState().toasts[0].message).toBe("Second");
  });

  it("auto-dismisses after timeout", () => {
    vi.useFakeTimers();
    toast("Will disappear");
    expect(useToastStore.getState().toasts).toHaveLength(1);

    vi.advanceTimersByTime(5000);
    expect(useToastStore.getState().toasts).toHaveLength(0);

    vi.useRealTimers();
  });

  it("assigns unique ids", () => {
    toast("A");
    toast("B");
    const [a, b] = useToastStore.getState().toasts;
    expect(a.id).not.toBe(b.id);
  });
});
