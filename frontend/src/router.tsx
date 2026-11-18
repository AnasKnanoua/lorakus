import type { QueryClient } from "@tanstack/react-query";
import {
  type RouterHistory,
  Outlet,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  redirect,
  useParams,
} from "@tanstack/react-router";

import { LoginScreen } from "@/features/auth/LoginScreen";
import { ChatLayout } from "@/features/chat/ChatLayout";
import { ConversationScreen } from "@/features/chat/ConversationScreen";
import { NewConversationScreen } from "@/features/chat/NewConversationScreen";
import { CalendarsScreen } from "@/features/calendars/CalendarsScreen";
import { DataScreen } from "@/features/data/DataScreen";
import { MemoryScreen } from "@/features/memory/MemoryScreen";
import { meQuery } from "@/lib/queries";

interface RouterContext {
  queryClient: QueryClient;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({ component: Outlet });

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/connexion",
  beforeLoad: async ({ context }) => {
    if (await context.queryClient.query(meQuery)) {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- API du routeur
      throw redirect({ to: "/" });
    }
  },
  component: LoginScreen,
});

// Toutes les pages de l'application exigent une session.
const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  beforeLoad: async ({ context }) => {
    if (!(await context.queryClient.query(meQuery))) {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- API du routeur
      throw redirect({ to: "/connexion" });
    }
  },
  component: ChatLayout,
});

const homeRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/",
  component: NewConversationScreen,
});

function ConversationRoute() {
  const { conversationId } = useParams({ from: "/app/c/$conversationId" });
  // Un ecran neuf par conversation : rien du tour en direct precedent ne la suit.
  return <ConversationScreen key={conversationId} />;
}

const conversationRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/c/$conversationId",
  component: ConversationRoute,
});

const memoryRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/memoire",
  component: MemoryScreen,
});

// Mes donnees (PR 41) : export et suppression, depuis l'icone du pied de la barre laterale.
const dataRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/donnees",
  component: DataScreen,
});

// Calendriers (PR 45) : abonnements ICS, dans le groupe « Outils » de la barre laterale.
const calendarsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/calendriers",
  component: CalendarsScreen,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  appRoute.addChildren([homeRoute, conversationRoute, memoryRoute, dataRoute, calendarsRoute]),
]);

/** history : barre d'adresse du navigateur par defaut ; historique en memoire dans les tests. */
export function makeRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: false,
    // Fondu bref entre les ecrans ; l'accueil fait en plus glisser le champ de saisie.
    defaultViewTransition: true,
    ...(history ? { history } : {}),
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof makeRouter>;
  }
}
