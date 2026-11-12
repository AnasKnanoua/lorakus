import { Link } from "@tanstack/react-router";
import { Menu, PanelLeftOpen, SquarePen } from "lucide-react";
import { createContext, useContext, type ReactNode } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/cn";

/** Etat partage de la mise en page : panneau mobile et barre laterale repliee (ordinateur). */
export interface LayoutState {
  openDrawer: () => void;
  sidebarCollapsed: boolean;
  expandSidebar: () => void;
}

export const LayoutContext = createContext<LayoutState>({
  openDrawer: () => undefined,
  sidebarCollapsed: false,
  expandSidebar: () => undefined,
});

/**
 * Barre du haut de chaque ecran : commandes communes a gauche (menu sur telephone ;
 * reouverture de la barre laterale et nouvelle conversation quand elle est repliee), puis le
 * contenu propre a l'ecran. Transparente, sans ligne de separation.
 */
export function TopBar({ children, actions }: { children?: ReactNode; actions?: ReactNode }) {
  const { openDrawer, sidebarCollapsed, expandSidebar } = useContext(LayoutContext);
  return (
    <header className="relative z-10 flex h-14 shrink-0 items-center gap-1 px-2 sm:px-3">
      <Button
        variant="quiet"
        size="icon"
        aria-label="Ouvrir la liste des conversations"
        onClick={openDrawer}
        className="lg:hidden"
      >
        <Menu aria-hidden="true" />
      </Button>
      {sidebarCollapsed && (
        <div className="hidden items-center gap-1 lg:flex">
          <Button variant="quiet" size="icon" aria-label="Afficher la barre latérale" onClick={expandSidebar}>
            <PanelLeftOpen aria-hidden="true" />
          </Button>
          <Link
            to="/"
            aria-label="Nouvelle conversation"
            className={buttonVariants({ variant: "quiet", size: "icon" })}
          >
            <SquarePen aria-hidden="true" />
          </Link>
        </div>
      )}
      <div className={cn("min-w-0 flex-1 px-1")}>{children}</div>
      {actions}
      <Link
        to="/"
        aria-label="Nouvelle conversation"
        className={cn(buttonVariants({ variant: "quiet", size: "icon" }), "lg:hidden")}
      >
        <SquarePen aria-hidden="true" />
      </Link>
    </header>
  );
}
