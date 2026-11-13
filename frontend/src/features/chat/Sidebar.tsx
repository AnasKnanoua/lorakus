import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { LogOut, PanelLeftClose, SquarePen } from "lucide-react";
import { useState } from "react";

import { logout } from "@/api/auth";
import { Collapsible } from "@/components/Collapsible";
import { Orb } from "@/components/Orb";
import { Button } from "@/components/ui/button";
import { groupByRecency } from "@/lib/dates";
import { conversationsQuery, factsQuery, meQuery } from "@/lib/queries";
import { NAV_GROUP_LABELS, NAV_ITEMS, type NavItem } from "@/navigation";

/** Conversations affichees d'abord ; « Afficher plus » en ajoute autant. */
const PAGE = 25;

const ROW =
  "flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[0.875rem] text-ink-muted transition-colors duration-150 hover:bg-hover hover:text-ink";

/**
 * Barre laterale, en trois etages stables (docs/frontend.md, « Navigation ») :
 * 1. action principale (nouvelle conversation) et destinations de l'assistant (src/navigation.ts) ;
 * 2. conversations, groupees par anciennete, seule partie qui defile ;
 * 3. profil et deconnexion (futurs reglages).
 * onCollapse : bouton de repli (ordinateur) ; onNavigate : fermeture du panneau (telephone).
 */
export function Sidebar({ onNavigate, onCollapse }: { onNavigate?: () => void; onCollapse?: () => void }) {
  const conversations = useQuery(conversationsQuery);
  const me = useQuery(meQuery);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [shown, setShown] = useState(PAGE);
  const email = me.data?.email ?? "";
  const all = conversations.data ?? [];
  const groups = groupByRecency(all.slice(0, shown), (c) => c.updated_at);
  const tools = NAV_ITEMS.filter((item) => item.group === "tools");

  async function signOut() {
    await logout();
    queryClient.clear(); // y compris l'utilisateur en cache : plus rien du compte en memoire
    await navigate({ to: "/connexion" });
  }

  return (
    <nav aria-label="Navigation principale" className="flex h-full flex-col bg-surface">
      <div className="flex h-14 shrink-0 items-center gap-2.5 pr-2 pl-4">
        <Orb className="size-[22px]" />
        <span className="flex-1 text-[1.0625rem] font-semibold tracking-[-0.01em]">Lorakus</span>
        {onCollapse && (
          <Button variant="quiet" size="icon-sm" aria-label="Masquer la barre latérale" onClick={onCollapse}>
            <PanelLeftClose aria-hidden="true" />
          </Button>
        )}
      </div>

      <div className="flex flex-col gap-0.5 px-2 pb-2">
        <Link to="/" onClick={onNavigate} className={`${ROW} font-medium text-ink`}>
          <SquarePen aria-hidden="true" className="size-4 text-accent" />
          Nouvelle conversation
        </Link>
        {NAV_ITEMS.filter((item) => item.group === "assistant").map((item) => (
          <NavLink key={item.id} item={item} onNavigate={onNavigate} />
        ))}
        {tools.length > 0 && (
          <Collapsible title={NAV_GROUP_LABELS.tools} defaultOpen={false} headerClassName="px-2.5">
            {tools.map((item) => (
              <NavLink key={item.id} item={item} onNavigate={onNavigate} />
            ))}
          </Collapsible>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-3">
        {groups.map((group) => (
          <section key={group.label} aria-label={group.label} className="pt-3">
            <h2 className="px-2.5 pb-1 text-xs font-medium text-ink-faint">{group.label}</h2>
            <ul>
              {group.items.map((c) => (
                <li key={c.id}>
                  <Link
                    to="/c/$conversationId"
                    params={{ conversationId: c.id }}
                    onClick={onNavigate}
                    title={c.title}
                    className="block truncate rounded-lg px-2.5 py-1.5 text-[0.875rem] text-ink-muted transition-colors duration-150 hover:bg-hover hover:text-ink"
                    activeProps={{ className: "bg-hover !text-ink", "aria-current": "page" }}
                  >
                    {c.title}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {all.length > shown && (
          <button
            type="button"
            onClick={() => {
              setShown((n) => n + PAGE);
            }}
            className="mt-1 w-full rounded-lg px-2.5 py-1.5 text-left text-[0.8125rem] text-ink-faint transition-colors hover:bg-hover hover:text-ink"
          >
            Afficher plus ({all.length - shown})
          </button>
        )}
        {conversations.data?.length === 0 && (
          <p className="px-2.5 pt-3 text-[0.875rem] text-ink-faint">Aucune conversation pour l'instant.</p>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-2.5 border-t border-line/60 px-3 py-2.5 pb-[max(0.625rem,env(safe-area-inset-bottom))]">
        <span
          aria-hidden="true"
          className="grid size-7 shrink-0 place-items-center rounded-full bg-gradient-to-br from-accent to-violet text-xs font-semibold text-accent-ink"
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

function NavLink({ item, onNavigate }: { item: NavItem; onNavigate?: (() => void) | undefined }) {
  const facts = useQuery({ ...factsQuery, enabled: item.id === "memory" });
  const badge = item.id === "memory" ? (facts.data?.filter((f) => f.status === "proposed").length ?? 0) : 0;
  const Icon = item.icon;
  return (
    <Link to={item.to} onClick={onNavigate} className={ROW} activeProps={{ className: "bg-hover !text-ink", "aria-current": "page" }}>
      <Icon aria-hidden="true" className="size-4" />
      <span className="flex-1">{item.label}</span>
      {badge > 0 && (
        <span className="min-w-5 rounded-full bg-accent-soft px-1.5 text-center text-[0.75rem] leading-5 font-semibold text-accent tabular-nums">
          {badge}
          <span className="sr-only"> à confirmer</span>
        </span>
      )}
    </Link>
  );
}
