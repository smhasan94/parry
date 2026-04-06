import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ClerkProvider } from "@clerk/clerk-react";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Toaster, toast } from "./components/ui/toast";
import { App } from "./App";
import { ApiError } from "./lib/api";
import { initSentry, Sentry } from "./lib/sentry";
import "./index.css";

initSentry();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
  mutationCache: new MutationCache({
    onError: (error) => {
      if (error instanceof ApiError) {
        toast(error.message || `Request failed (${error.status})`);
        // Only report 5xx — 4xx are user errors and not actionable
        if (error.status >= 500) {
          Sentry.captureException(error);
        }
      } else {
        toast(error.message || "An unexpected error occurred");
        Sentry.captureException(error);
      }
    },
  }),
});

const clerkPubKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
if (!clerkPubKey) {
  throw new Error(
    "Missing VITE_CLERK_PUBLISHABLE_KEY environment variable. " +
    "Copy .env.example to .env and fill in your Clerk publishable key."
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <ClerkProvider publishableKey={clerkPubKey}>
        <QueryClientProvider client={queryClient}>
          <App />
          <Toaster />
        </QueryClientProvider>
      </ClerkProvider>
    </ErrorBoundary>
  </StrictMode>
);
