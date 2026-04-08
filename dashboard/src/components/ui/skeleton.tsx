import { cn } from "@/lib/utils";

/**
 * Rectangular shimmer placeholder. Use inside cards to preserve
 * layout during data fetches so pages don't snap on load.
 *
 * Shape it with Tailwind width/height utilities:
 *
 *     <Skeleton className="h-4 w-32" />
 *     <Skeleton className="h-9 w-full rounded-md" />
 *
 * The shimmer uses Tailwind's animate-pulse — no new CSS keyframes,
 * no extra deps. A subtle gradient on top of the base muted colour
 * reads as "loading" without being visually noisy on a dark UI.
 */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-gradient-to-r from-muted/30 via-muted/50 to-muted/30",
        className,
      )}
      {...props}
    />
  );
}

/**
 * Stack of N skeleton lines separated by the given gap. Convenient
 * when you just want a placeholder-ish shape inside a Card body.
 */
export function SkeletonLines({
  count = 3,
  gap = "gap-2",
  lineHeight = "h-4",
}: {
  count?: number;
  gap?: string;
  lineHeight?: string;
}) {
  return (
    <div className={cn("flex flex-col", gap)}>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn(
            lineHeight,
            // Randomish-feeling widths without actually being
            // non-deterministic (SSR-safe).
            i === count - 1 ? "w-4/5" : i % 2 === 0 ? "w-full" : "w-11/12",
          )}
        />
      ))}
    </div>
  );
}
