import "./styles.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { makeQueryClient, returnToLogin } from "@/lib/queryClient";

import { makeRouter } from "./router";

const queryClient = makeQueryClient(() => {
  returnToLogin(queryClient, () => router.navigate({ to: "/connexion" }));
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
