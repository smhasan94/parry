import { RouterProvider } from "@tanstack/react-router";
import { useAuth } from "@clerk/clerk-react";
import { useEffect } from "react";
import { router } from "./routes/router";
import { api } from "./lib/api";

export function App() {
  const { getToken, isSignedIn, isLoaded } = useAuth();

  useEffect(() => {
    if (isLoaded && isSignedIn) {
      // Pass the getter so every API request fetches a fresh token
      api.setTokenGetter(() => getToken());
    }
  }, [isLoaded, isSignedIn, getToken]);

  if (!isLoaded) {
    return null;
  }

  return <RouterProvider router={router} />;
}
