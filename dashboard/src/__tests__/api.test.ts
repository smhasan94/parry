import { describe, it, expect } from "vitest";
import { ApiError } from "@/lib/api";

describe("ApiError", () => {
  it("stores status and message", () => {
    const err = new ApiError(401, "Unauthorized", "AUTH_FAILED");
    expect(err.status).toBe(401);
    expect(err.message).toBe("Unauthorized");
    expect(err.code).toBe("AUTH_FAILED");
    expect(err.name).toBe("ApiError");
  });

  it("is an instance of Error", () => {
    const err = new ApiError(500, "Server error");
    expect(err).toBeInstanceOf(Error);
  });

  it("works without code", () => {
    const err = new ApiError(404, "Not found");
    expect(err.code).toBeUndefined();
  });
});
