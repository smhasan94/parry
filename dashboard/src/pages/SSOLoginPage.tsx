import { useState } from "react";
import { api } from "@/lib/api";
import { Shield, LogIn, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Standalone SSO login page at /auth/sso.
 *
 * Users enter their organization slug (Clerk org id) and get
 * redirected to their IdP via WorkOS.
 */
export function SSOLoginPage() {
  const [orgSlug, setOrgSlug] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!orgSlug.trim()) return;

    setLoading(true);
    setError("");
    try {
      const { authorization_url } = await api.ssoLogin({
        org_slug: orgSlug.trim(),
      });
      window.location.href = authorization_url;
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to initiate SSO login",
      );
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <div className="flex justify-center">
            <Shield className="h-10 w-10 text-primary" />
          </div>
          <h1 className="mt-4 text-xl font-bold">Sign in with SSO</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Enter your organization identifier to continue via SAML
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="org-slug"
              className="block text-sm font-medium text-foreground"
            >
              Organization ID
            </label>
            <Input
              id="org-slug"
              value={orgSlug}
              onChange={(e) => setOrgSlug(e.target.value)}
              placeholder="acme-corp"
              className="mt-1"
              autoFocus
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              {error}
            </div>
          )}

          <Button
            type="submit"
            className="w-full"
            disabled={loading || !orgSlug.trim()}
          >
            <LogIn className="mr-2 h-4 w-4" />
            {loading ? "Redirecting..." : "Continue with SSO"}
          </Button>
        </form>

        <div className="text-center">
          <a
            href="/"
            className="text-xs text-muted-foreground underline hover:text-foreground"
          >
            Sign in with email instead
          </a>
        </div>
      </div>
    </div>
  );
}
