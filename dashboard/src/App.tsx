import { RouterProvider } from "@tanstack/react-router";
import { SignIn, useAuth } from "@clerk/clerk-react";
import { useEffect } from "react";
import { router } from "./routes/router";
import { api } from "./lib/api";

/** SSO routes bypass the Clerk auth gate — they run before the user has a session. */
function isSSORoute(): boolean {
  return window.location.pathname.startsWith("/auth/sso");
}

export function App() {
  const { getToken, isSignedIn, isLoaded } = useAuth();

  useEffect(() => {
    if (isLoaded && isSignedIn) {
      api.setTokenGetter(() => getToken());
    }
  }, [isLoaded, isSignedIn, getToken]);

  if (!isLoaded) {
    return null;
  }

  // SSO pages run outside the auth gate — the user is authenticating
  // via SAML and doesn't have a Clerk session yet.
  if (isSSORoute()) {
    return <RouterProvider router={router} />;
  }

  if (!isSignedIn) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="space-y-4 text-center">
          <SignIn />
          <a
            href="/auth/sso"
            className="inline-block text-xs text-muted-foreground underline hover:text-foreground"
          >
            Sign in with SAML SSO
          </a>
        </div>
      </div>
    );
  }

  return <RouterProvider router={router} />;
}
