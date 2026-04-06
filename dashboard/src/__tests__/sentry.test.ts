import { describe, it, expect, vi, afterEach } from "vitest";
import { filterBreadcrumb, initSentry } from "@/lib/sentry";

describe("filterBreadcrumb", () => {
  it("filters Authorization header on fetch breadcrumbs", () => {
    const result = filterBreadcrumb({
      category: "fetch",
      data: {
        request_headers: {
          Authorization: "Bearer real-token",
          "Content-Type": "application/json",
        },
      },
    });
    const headers = (result.data as { request_headers: Record<string, string> }).request_headers;
    expect(headers.Authorization).toBe("[Filtered]");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("filters X-Parry-Secret on fetch breadcrumbs", () => {
    const result = filterBreadcrumb({
      category: "fetch",
      data: { request_headers: { "X-Parry-Secret": "sk-parry-real" } },
    });
    const headers = (result.data as { request_headers: Record<string, string> }).request_headers;
    expect(headers["X-Parry-Secret"]).toBe("[Filtered]");
  });

  it("filters Cookie header on fetch breadcrumbs", () => {
    const result = filterBreadcrumb({
      category: "fetch",
      data: { request_headers: { Cookie: "session=abc" } },
    });
    const headers = (result.data as { request_headers: Record<string, string> }).request_headers;
    expect(headers.Cookie).toBe("[Filtered]");
  });

  it("is case-insensitive when matching header names", () => {
    const result = filterBreadcrumb({
      category: "fetch",
      data: { request_headers: { authorization: "Bearer x", "x-parry-secret": "y" } },
    });
    const headers = (result.data as { request_headers: Record<string, string> }).request_headers;
    expect(headers.authorization).toBe("[Filtered]");
    expect(headers["x-parry-secret"]).toBe("[Filtered]");
  });

  it("also handles xhr breadcrumbs", () => {
    const result = filterBreadcrumb({
      category: "xhr",
      data: { request_headers: { Authorization: "Bearer x" } },
    });
    const headers = (result.data as { request_headers: Record<string, string> }).request_headers;
    expect(headers.Authorization).toBe("[Filtered]");
  });

  it("leaves non-network breadcrumbs unchanged", () => {
    const breadcrumb = { category: "ui.click", message: "button clicked" };
    expect(filterBreadcrumb(breadcrumb)).toEqual({
      category: "ui.click",
      message: "button clicked",
    });
  });

  it("handles fetch breadcrumb without request_headers", () => {
    const breadcrumb = { category: "fetch", data: { url: "/api/v1/agents" } };
    expect(filterBreadcrumb(breadcrumb)).toEqual(breadcrumb);
  });

  it("handles fetch breadcrumb without data", () => {
    const breadcrumb = { category: "fetch" };
    expect(filterBreadcrumb(breadcrumb)).toEqual(breadcrumb);
  });
});

describe("initSentry", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("returns false when VITE_SENTRY_DSN is empty", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "");
    expect(initSentry()).toBe(false);
  });

  it("returns false when VITE_SENTRY_DSN is undefined", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "");
    expect(initSentry()).toBe(false);
  });
});
