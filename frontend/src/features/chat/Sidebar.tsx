import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { LogOut, PanelLeftClose, SquarePen } from "lucide-react";
import { useState } from "react";

import { logout } from "@/api/auth";
import { Collapsible } from "@/components/Collapsible";
import { Button } from "@/components/ui/button";
import { groupByRecency } from "@/lib/dates";
import { conversationsQuery, factsQuery, meQuery } from "@/lib/queries";
import { NAV_GROUP_LABELS, NAV_ITEMS, type NavItem } from "@/navigation";

/** Conversations affichees d'abord ; « Afficher plus » en ajoute autant. */
const PAGE = 25;

/*
 * Une ligne de la barre laterale (docs/frontend.md, « Navigation ») : 40 px de haut, forme de
 * pilule, texte de 15 px. L'icone (18 px) et le texte des conversations commencent au meme
 * bord gauche, comme les titres de section : une seule ligne de lecture verticale.
 */
const ROW =
  "flex h-10 items-center gap-3 rounded-full px-3 text-base text-ink-muted transition-colors duration-150 hover:bg-hover hover:text-ink";
const ACTIVE = { className: "bg-hover !text-ink font-medium", "aria-current": "page" } as const;

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
      <div className="flex h-14 shrink-0 items-center pr-2 pl-5">
        <span className="flex-1 text-lg font-semibold">Lorakus</span>
        {onCollapse && (
          <Button variant="quiet" size="icon-sm" aria-label="Masquer la barre latérale" onClick={onCollapse}>
            <PanelLeftClose aria-hidden="true" />
          </Button>
        )}
      </div>

      <div className="flex flex-col gap-0.5 px-2 pt-1 pb-2">
        {/* Action principale : seule ligne avec un fond permanent. */}
        <Link to="/" onClick={onNavigate} className={`${ROW} mb-1 bg-raised font-medium text-ink hover:bg-hover`}>
          <SquarePen aria-hidden="true" className="size-[18px]" />
          Nouvelle conversation
        </Link>
        {NAV_ITEMS.filter((item) => item.group === "assistant").map((item) => (
          <NavLink key={item.id} item={item} onNavigate={onNavigate} />
        ))}
        {tools.length > 0 && (
          <Collapsible title={NAV_GROUP_LABELS.tools} defaultOpen={false} headerClassName="px-3">
            {tools.map((item) => (
              <NavLink key={item.id} item={item} onNavigate={onNavigate} />
            ))}
          </Collapsible>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-4">
        {groups.map((group) => (
          <section key={group.label} aria-label={group.label} className="pt-5 first:pt-3">
            <h2 className="px-3 pb-1.5 text-sm font-medium text-ink-faint">{group.label}</h2>
            <ul className="flex flex-col gap-px">
              {group.items.map((c) => (
                <li key={c.id}>
                  <Link
                    to="/c/$conversationId"
                    params={{ conversationId: c.id }}
                    onClick={onNavigate}
                    title={c.title}
                    className="flex h-10 items-center rounded-full px-3 text-base text-ink-muted transition-colors duration-150 hover:bg-hover hover:text-ink"
                    activeProps={ACTIVE}
                  >
                    <span className="truncate">{c.title}</span>
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
            className="mt-1 flex h-10 w-full items-center rounded-full px-3 text-left text-sm text-ink-faint transition-colors hover:bg-hover hover:text-ink"
          >
            Afficher plus ({all.length - shown})
          </button>
        )}
        {conversations.data?.length === 0 && (
          <p className="px-3 pt-4 text-sm text-ink-faint">Aucune conversation pour l'instant.</p>
        )}
      </div>

      {/* Compte : sans bordure, aligne sur les lignes au-dessus ; les reglages viendront ici. */}
      <div className="flex shrink-0 items-center gap-3 px-2 pt-1 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        <div className="flex min-w-0 flex-1 items-center gap-3 px-1.5">
          <span
            aria-hidden="true"
            className="grid size-8 shrink-0 place-items-center rounded-full bg-accent-soft text-sm font-semibold text-accent"
          >
            {email.charAt(0).toUpperCase() || "?"}
          </span>
          <span className="min-w-0 flex-1 truncate text-sm text-ink-muted" title={email}>
            {email}
          </span>
        </div>
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
    <Link to={item.to} onClick={onNavigate} className={ROW} activeProps={ACTIVE}>
      <Icon aria-hidden="true" className="size-[18px]" />
      <span className="flex-1">{item.label}</span>
      {badge > 0 && (
        <span className="min-w-5 rounded-full bg-accent-soft px-1.5 text-center text-xs leading-5 font-semibold text-accent tabular-nums">
          {badge}
          <span className="sr-only"> à confirmer</span>
        </span>
      )}
    </Link>
  );
}
