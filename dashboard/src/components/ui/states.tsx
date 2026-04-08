import { AlertCircle, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Shared loading / error / empty state primitives.
 *
 * Dashboard pages were inconsistent: some showed "Loading…" text,
 * some showed nothing on error, some had bespoke empty states per
 * page. These helpers give every page the same vocabulary so the
 * differences between pages land on content, not chrome.
 *
 * Usage:
 *
 *     const { data, isLoading, isError, error, refetch } = useQuery(...)
 *     if (isLoading) return <LoadingState label="Loading incidents" />
 *     if (isError)   return <ErrorState error={error} onRetry={refetch} />
 *     if (!data?.length) return <EmptyState icon={...} title={...} body={...} />
 *
 * They're presentational — no data fetching, no hooks. Pass in
 * whatever state the page already has on hand.
 */

interface LoadingStateProps {
  label?: string;
  className?: string;
}

export function LoadingState({
  label = "Loading…",
  className,
}: LoadingStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 py-10 text-center",
        className,
      )}
      role="status"
      aria-live="polite"
    >
      <div
        className="h-6 w-6 animate-spin rounded-full border-2 border-muted border-t-primary"
        aria-hidden="true"
      />
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}

interface ErrorStateProps {
  error?: unknown;
  title?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  error,
  title = "Something went wrong",
  onRetry,
  className,
}: ErrorStateProps) {
  const detail = extractMessage(error);
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 py-10 text-center",
        className,
      )}
      role="alert"
    >
      <AlertCircle className="h-8 w-8 text-red-400" aria-hidden="true" />
      <p className="text-sm font-medium">{title}</p>
      {detail && (
        <p className="max-w-md text-xs text-muted-foreground">{detail}</p>
      )}
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCcw className="h-3.5 w-3.5" />
          Retry
        </Button>
      )}
    </div>
  );
}

interface EmptyStateProps {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  body?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  body,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 py-10 text-center",
        className,
      )}
    >
      {Icon && <Icon className="h-10 w-10 text-muted-foreground" aria-hidden="true" />}
      <p className="text-sm font-medium">{title}</p>
      {body && <p className="max-w-md text-xs text-muted-foreground">{body}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/**
 * Pull a human-readable message out of whatever the query layer
 * hands us. TanStack Query surfaces ApiError instances (with our
 * own message) and plain Error instances. Anything else we render
 * as nothing rather than "[object Object]".
 */
function extractMessage(error: unknown): string | null {
  if (!error) return null;
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return null;
}
