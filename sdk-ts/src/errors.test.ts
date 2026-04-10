import { describe, it, expect } from "vitest";
import { ParryBlockedError, ParryPermissionDeniedError } from "./errors.js";

describe("ParryBlockedError", () => {
  it("stores all fields", () => {
    const err = new ParryBlockedError({
      reason: "Prompt injection detected",
      detector: "prompt_injection",
      severity: "high",
      confidence: 0.92,
    });
    expect(err.reason).toBe("Prompt injection detected");
    expect(err.detector).toBe("prompt_injection");
    expect(err.severity).toBe("high");
    expect(err.confidence).toBe(0.92);
    expect(err.name).toBe("ParryBlockedError");
  });

  it("includes detector in message", () => {
    const err = new ParryBlockedError({
      reason: "test",
      detector: "jailbreak",
      severity: "critical",
      confidence: 0.99,
    });
    expect(err.message).toContain("jailbreak");
    expect(err.message).toContain("test");
  });

  it("is an instance of Error", () => {
    const err = new ParryBlockedError({
      reason: "test",
      detector: "test",
      severity: "low",
      confidence: 0.5,
    });
    expect(err).toBeInstanceOf(Error);
  });
});

describe("ParryPermissionDeniedError", () => {
  it("is a subclass of ParryBlockedError", () => {
    const err = new ParryPermissionDeniedError({
      reason: "Tool blocked",
    });
    expect(err).toBeInstanceOf(ParryBlockedError);
    expect(err).toBeInstanceOf(Error);
  });

  it("has permission_boundary detector", () => {
    const err = new ParryPermissionDeniedError({
      reason: "Not allowed",
    });
    expect(err.detector).toBe("permission_boundary");
    expect(err.severity).toBe("high");
    expect(err.confidence).toBe(1.0);
  });

  it("stores tool name", () => {
    const err = new ParryPermissionDeniedError({
      reason: "Blocked",
      toolName: "delete_account",
    });
    expect(err.toolName).toBe("delete_account");
    expect(err.name).toBe("ParryPermissionDeniedError");
  });

  it("defaults toolName to null", () => {
    const err = new ParryPermissionDeniedError({ reason: "test" });
    expect(err.toolName).toBeNull();
  });
});
