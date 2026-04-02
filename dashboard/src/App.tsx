import { RouterProvider } from "@tanstack/react-router";
import { SignIn, useAuth } from "@clerk/clerk-react";
import { useEffect } from "react";
import { router } from "./routes/router";
import { api } from "./lib/api";

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

  if (!isSignedIn) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <SignIn />
      </div>
    );
  }

  return <RouterProvider router={router} />;
}
