import * as Sentry from "@sentry/react";

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
    // Performance tracing — sample 10% in prod
    tracesSampleRate: import.meta.env.MODE === "production" ? 0.1 : 1.0,
    // Don't ship session replays by default — privacy-sensitive
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    // Strip Authorization headers in network breadcrumbs
    beforeBreadcrumb(breadcrumb) {
      if (breadcrumb.category === "fetch" || breadcrumb.category === "xhr") {
        const data = breadcrumb.data as { request_headers?: Record<string, string> } | undefined;
        if (data?.request_headers) {
          for (const k of Object.keys(data.request_headers)) {
            if (
              k.toLowerCase() === "authorization" ||
              k.toLowerCase() === "x-parry-secret"
            ) {
              data.request_headers[k] = "[Filtered]";
            }
          }
        }
      }
      return breadcrumb;
    },
  });

  return true;
}

export { Sentry };
