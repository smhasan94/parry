import { useEffect, useState } from "react";
import { useSignIn } from "@clerk/clerk-react";
import { api } from "@/lib/api";
import { Shield, Loader2, AlertCircle } from "lucide-react";

/**
 * Handles the WorkOS SAML callback redirect.
 *
 * Flow:
 * 1. Extract `code` from URL query params
 * 2. Exchange code for profile via backend `/sso/callback`
 * 3. Get Clerk sign-in ticket via `/sso/session`
 * 4. Mint Clerk session via `signIn.create({ strategy: "ticket" })`
 * 5. Redirect to dashboard
 */
export function SSOCallbackPage() {
  const { signIn, isLoaded } = useSignIn();
  const [status, setStatus] = useState<"processing" | "error">("processing");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    if (!isLoaded) return;

    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");

    if (!code) {
      setStatus("error");
      setErrorMessage("Missing authorization code in callback URL");
      return;
    }

    handleCallback(code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded]);

  async function handleCallback(code: string) {
    try {
      // Step 1: Exchange code for profile
      const profile = await api.ssoCallback(code);

      // Step 2: Get Clerk sign-in ticket
      const { ticket } = await api.ssoCreateSession({
        workos_user_id: profile.workos_user_id,
        email: profile.email,
        org_id: profile.org_id,
      });

      // Step 3: Create Clerk session
      if (!signIn) {
        throw new Error("Clerk signIn not available");
      }

      const result = await signIn.create({
        strategy: "ticket",
        ticket,
      });

      if (result.status === "complete") {
        // Session created — redirect to dashboard
        window.location.href = "/dashboard";
      } else {
        setStatus("error");
        setErrorMessage("Clerk session creation returned unexpected status");
      }
    } catch (err) {
      setStatus("error");
      setErrorMessage(
        err instanceof Error ? err.message : "SSO login failed",
      );
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 text-center">
        <div className="flex justify-center">
          <Shield className="h-10 w-10 text-primary" />
        </div>

        {status === "processing" ? (
          <>
            <Loader2 className="mx-auto h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              Completing SSO login...
            </p>
          </>
        ) : (
          <>
            <AlertCircle className="mx-auto h-8 w-8 text-destructive" />
            <div className="space-y-2">
              <p className="text-sm font-medium text-destructive">
                SSO Login Failed
              </p>
              <p className="text-xs text-muted-foreground">{errorMessage}</p>
            </div>
            <a
              href="/"
              className="inline-block text-sm text-primary underline hover:no-underline"
            >
              Back to login
            </a>
          </>
        )}
      </div>
    </div>
  );
}
