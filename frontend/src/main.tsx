import "./styles.css";

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ApiError } from "@/api/client";

import { makeRouter } from "./router";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 2,
      refetchOnWindowFocus: false,
    },
  },
  queryCache: new QueryCache({
    // Session expiree pendant l'utilisation : retour a l'ecran de connexion.
    onError: (error) => {
      if (error instanceof ApiError && error.status === 401) {
        queryClient.clear();
        void router.navigate({ to: "/connexion" });
      }
    },
  }),
});

const router = makeRouter(queryClient);

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
}

// Application installable : le service worker n'existe qu'en production (pas avec vite dev).
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js", { scope: "/" });
  });
}
