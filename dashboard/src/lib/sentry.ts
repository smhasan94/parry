import * as Sentry from "@sentry/react";

const SENSITIVE_HEADERS = ["authorization", "x-parry-secret", "cookie"];

/**
 * Strip sensitive headers (Authorization, X-Parry-Secret, Cookie) from network
 * breadcrumbs before they get sent to Sentry. Returns the breadcrumb mutated
 * in-place. Exported for unit testing.
 */
export function filterBreadcrumb<T extends { category?: string; data?: unknown }>(
  breadcrumb: T
): T {
  if (breadcrumb.category !== "fetch" && breadcrumb.category !== "xhr") {
    return breadcrumb;
  }
  const data = breadcrumb.data as { request_headers?: Record<string, string> } | undefined;
  if (!data?.request_headers) return breadcrumb;
  for (const k of Object.keys(data.request_headers)) {
    if (SENSITIVE_HEADERS.includes(k.toLowerCase())) {
      data.request_headers[k] = "[Filtered]";
    }
  }
  return breadcrumb;
}

/**
 * Initialize Sentry. No-ops when VITE_SENTRY_DSN is unset.
 * Returns true if Sentry was initialized, false otherwise.
 */
export function initSentry(): boolean {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return false;

  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    tracesSampleRate: import.meta.env.MODE === "production" ? 0.1 : 1.0,
    // Don't ship session replays by default — privacy-sensitive
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    beforeBreadcrumb(breadcrumb) {
      return filterBreadcrumb(breadcrumb);
    },
  });

  return true;
}

export { Sentry };
