import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Outlet } from "@tanstack/react-router";
import { useCallback, useMemo, useState } from "react";

import { AssistantDisabledError } from "@/api/assistant";
import { Orb } from "@/components/Orb";
import { cn } from "@/lib/cn";
import { conversationsQuery } from "@/lib/queries";
import { useSwipeToClose, useSwipeToOpen } from "@/lib/useSwipeToClose";

import { EnableAssistant } from "./EnableAssistant";
import { LayoutContext } from "./layout";
import { Sidebar } from "./Sidebar";

const COLLAPSED_KEY = "lorakus.sidebar.collapsed";

/** Preference d'affichage seulement (aucune donnee personnelle) ; stockage facultatif. */
function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Mise en page : barre laterale repliable sur grand ecran, panneau coulissant sur telephone.
 * La zone principale n'affiche rien tant qu'on ne sait pas si l'assistant est active : sinon
 * l'accueil s'affichait un instant avant l'ecran d'activation.
 */
export function ChatLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const conversations = useQuery(conversationsQuery);
  const disabled = conversations.error instanceof AssistantDisabledError;
  const swipe = useSwipeToClose(() => {
    setDrawerOpen(false);
  });
  const swipeOpen = useSwipeToOpen(() => {
    setDrawerOpen(true);
  });

  const setSidebar = useCallback((value: boolean) => {
    setCollapsed(value);
    try {
      window.localStorage.setItem(COLLAPSED_KEY, value ? "1" : "0");
    } catch {
      // Stockage indisponible : la preference vaut pour cette session seulement.
    }
  }, []);

  const layout = useMemo(
    () => ({
      openDrawer: () => {
        setDrawerOpen(true);
      },
      sidebarCollapsed: collapsed,
      expandSidebar: () => {
        setSidebar(false);
      },
    }),
    [collapsed, setSidebar],
  );

  return (
    <LayoutContext.Provider value={layout}>
      <div className="flex h-dvh overflow-hidden bg-background">
        <aside
          aria-hidden={collapsed}
          inert={collapsed}
          className={cn(
            "vt-sidebar hidden shrink-0 overflow-hidden transition-[width] duration-300 ease-[var(--ease-out-soft)] lg:block",
            collapsed ? "w-0" : "w-[280px]",
          )}
        >
          <div className="h-full w-[280px]">
            <Sidebar
              onCollapse={() => {
                setSidebar(true);
              }}
            />
          </div>
        </aside>

        <Dialog.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
          <Dialog.Portal>
            <Dialog.Overlay className="scrim fixed inset-0 z-40 bg-[var(--scrim)] backdrop-blur-[2px] lg:hidden" />
            <Dialog.Content
              aria-describedby={undefined}
              className="drawer fixed inset-y-0 left-0 z-50 w-[86%] max-w-[320px] shadow-float lg:hidden"
              {...swipe}
            >
              <Dialog.Title className="sr-only">Conversations</Dialog.Title>
              <Sidebar
                onNavigate={() => {
                  setDrawerOpen(false);
                }}
              />
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>

        <main className="vt-page relative flex min-w-0 flex-1 flex-col" {...swipeOpen}>
          {conversations.isPending ? (
            <div className="flex flex-1 items-center justify-center" aria-busy="true">
              <Orb thinking className="size-8" />
              <span className="sr-only">Chargement…</span>
            </div>
          ) : disabled ? (
            <EnableAssistant />
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    </LayoutContext.Provider>
  );
}
