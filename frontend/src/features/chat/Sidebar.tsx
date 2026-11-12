import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { LogOut, PanelLeftClose, SquarePen } from "lucide-react";

import { logout } from "@/api/auth";
import { Orb } from "@/components/Orb";
import { Button } from "@/components/ui/button";
import { conversationsQuery, meQuery } from "@/lib/queries";

/**
 * Barre laterale : marque, nouvelle conversation, conversations recentes, profil.
 * onCollapse : bouton de repli (ordinateur) ; onNavigate : fermeture du panneau (telephone).
 */
export function Sidebar({ onNavigate, onCollapse }: { onNavigate?: () => void; onCollapse?: () => void }) {
  const conversations = useQuery(conversationsQuery);
  const me = useQuery(meQuery);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const email = me.data?.email ?? "";

  async function signOut() {
    await logout();
    queryClient.clear(); // y compris l'utilisateur en cache : plus rien du compte en memoire
    await navigate({ to: "/connexion" });
  }

  return (
    <nav aria-label="Conversations" className="flex h-full flex-col bg-surface">
      <div className="flex h-14 shrink-0 items-center gap-2.5 pr-2 pl-4">
        <Orb className="size-[22px]" />
        <span className="flex-1 text-[1.0625rem] font-semibold tracking-[-0.01em]">Lorakus</span>
        {onCollapse && (
          <Button variant="quiet" size="icon-sm" aria-label="Masquer la barre latérale" onClick={onCollapse}>
            <PanelLeftClose aria-hidden="true" />
          </Button>
        )}
      </div>

      <div className="px-2.5 pt-1 pb-3">
        <Link
          to="/"
          onClick={onNavigate}
          className="group flex h-10 items-center gap-2.5 rounded-xl px-3 text-[0.9375rem] font-medium text-ink transition-colors hover:bg-hover"
        >
          <SquarePen aria-hidden="true" className="size-[18px] text-accent" />
          Nouvelle conversation
        </Link>
      </div>

      <p className="px-5 pb-1.5 text-xs font-medium text-ink-faint">Récentes</p>
      <ul className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-3">
        {conversations.data?.map((c) => (
          <li key={c.id}>
            <Link
              to="/c/$conversationId"
              params={{ conversationId: c.id }}
              onClick={onNavigate}
              title={c.title}
              className="block truncate rounded-lg px-3 py-2 text-[0.875rem] text-ink-muted transition-colors hover:bg-hover hover:text-ink"
              activeProps={{ className: "bg-hover !text-ink", "aria-current": "page" }}
            >
              {c.title}
            </Link>
          </li>
        ))}
        {conversations.data?.length === 0 && (
          <li className="px-3 py-2 text-[0.875rem] text-ink-faint">Aucune conversation pour l'instant.</li>
        )}
      </ul>

      <div className="flex shrink-0 items-center gap-3 px-3 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        <span
          aria-hidden="true"
          className="grid size-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-accent to-violet text-sm font-semibold text-accent-ink"
        >
          {email.charAt(0).toUpperCase() || "?"}
        </span>
        <span className="min-w-0 flex-1 truncate text-[0.8125rem] text-ink-muted" title={email}>
          {email}
        </span>
        <Button variant="quiet" size="icon-sm" aria-label="Se déconnecter" onClick={() => void signOut()}>
          <LogOut aria-hidden="true" />
        </Button>
      </div>
    </nav>
  );
}
