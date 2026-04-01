import { RouterProvider } from "@tanstack/react-router";
import { useAuth } from "@clerk/clerk-react";
import { useEffect } from "react";
import { router } from "./routes/router";
import { api } from "./lib/api";

export function App() {
  const { getToken, isSignedIn } = useAuth();

  useEffect(() => {
    if (isSignedIn) {
      getToken().then((token) => {
        if (token) api.setToken(token);
      });
    }
  }, [isSignedIn, getToken]);

  return <RouterProvider router={router} />;
}
