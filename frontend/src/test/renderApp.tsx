import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { render } from "@testing-library/react";

import { resetReplies } from "@/features/chat/replies";
import { makeRouter } from "@/router";

/** Monte l'application complete (routeur, requetes) sur une adresse donnee. */
export function renderApp(path = "/") {
  resetReplies();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = makeRouter(queryClient, createMemoryHistory({ initialEntries: [path] }));
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router, queryClient };
}
