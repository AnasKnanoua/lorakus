import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { render } from "@testing-library/react";

import { resetReplies } from "@/features/chat/replies";
import { makeQueryClient, returnToLogin } from "@/lib/queryClient";
import { makeRouter } from "@/router";

/** Monte l'application complete (routeur, requetes) sur une adresse donnee. */
export function renderApp(path = "/") {
  resetReplies();
  // Le meme client que l'application : les tests voient la vraie politique de nouvelle
  // tentative (un test sans elle laissait passer un ecran d'activation retarde).
  const queryClient = makeQueryClient(() => {
    returnToLogin(queryClient, () => router.navigate({ to: "/connexion" }));
  });
  const router = makeRouter(queryClient, createMemoryHistory({ initialEntries: [path] }));
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router, queryClient };
}
