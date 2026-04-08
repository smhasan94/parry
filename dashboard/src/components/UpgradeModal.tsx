import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Sparkles, X } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Global upgrade prompt mounted at the layout level.
 *
 * Listens for the `parry:upgrade-required` CustomEvent that
 * ApiClient.request() dispatches whenever the backend returns 402.
 * The modal is intentionally callable from anywhere — feature-gated
 * routes and quota-bound ingests both flow through the same handler.
 */
export function UpgradeModal() {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    function handler(e: Event) {
      const custom = e as CustomEvent<{ message?: string }>;
      setMessage(custom.detail?.message ?? "You've reached your plan limit.");
      setOpen(true);
    }
    window.addEventListener("parry:upgrade-required", handler as EventListener);
    return () =>
      window.removeEventListener("parry:upgrade-required", handler as EventListener);
  }, []);

  if (!open) return null;

  async function handleUpgrade() {
    setBusy(true);
    try {
      // Sends the user to Stripe checkout. The backend picks the
      // target price id from its configured Growth tier.
      const priceId = import.meta.env.VITE_STRIPE_PRICE_GROWTH || "growth";
      const returnBase = window.location.origin;
      const { url } = await api.createCheckoutSession(
        priceId,
        `${returnBase}/settings?upgrade=success`,
        `${returnBase}/settings?upgrade=cancelled`,
      );
      window.location.href = url;
    } catch {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <Card className="w-full max-w-md border-primary/30">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center justify-between text-base">
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              Upgrade Required
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{message}</p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
              Maybe later
            </Button>
            <Button size="sm" onClick={handleUpgrade} disabled={busy}>
              {busy ? "Redirecting…" : "Upgrade"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
