import { QueryCache, QueryClient } from "@tanstack/react-query";

import { AssistantDisabledError } from "@/api/assistant";
import { ApiError } from "@/api/client";

/**
 * Nouvelle tentative seulement quand elle peut changer quelque chose : une erreur reseau ou
 * serveur (5xx). Jamais pour une reponse definitive de l'API (4xx), ni pour le module
 * desactive : sinon l'ecran d'activation n'apparait qu'apres plusieurs secondes d'essais.
 */
export function shouldRetry(failures: number, error: unknown): boolean {
  if (error instanceof AssistantDisabledError) return false;
  if (error instanceof ApiError && error.status < 500) return false;
  return failures < 2;
}

/**
 * Client unique de l'application, partage par les tests : meme politique partout.
 * onUnauthorized : session expiree pendant l'utilisation (401 sur une requete).
 */
export function makeQueryClient(onUnauthorized: () => void): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
    queryCache: new QueryCache({
      onError: (error) => {
        if (error instanceof ApiError && error.status === 401) {
          onUnauthorized();
        }
      },
    }),
  });
}

/** Session expiree : on oublie toutes les donnees en memoire et on revient a la connexion. */
export function returnToLogin(queryClient: QueryClient, navigate: () => Promise<void>): void {
  queryClient.clear();
  void navigate();
}
