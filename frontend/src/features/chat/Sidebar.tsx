import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { LogOut, SquarePen } from "lucide-react";

import { logout } from "@/api/auth";
import { Monogram } from "@/components/Monogram";
import { Button, buttonVariants } from "@/components/ui/button";
import { conversationsQuery, meQuery } from "@/lib/queries";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const conversations = useQuery(conversationsQuery);
  const me = useQuery(meQuery);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  async function signOut() {
    await logout();
    queryClient.clear(); // y compris l'utilisateur en cache : plus rien du compte en memoire
    await navigate({ to: "/connexion" });
  }

  return (
    <nav aria-label="Conversations" className="flex h-full flex-col bg-surface">
      <div className="flex h-14 shrink-0 items-center gap-2 px-4">
        <Monogram />
        <span className="flex-1 text-lg font-bold">Lorakus</span>
        <Link
          to="/"
          aria-label="Nouvelle conversation"
          onClick={onNavigate}
          className={buttonVariants({ variant: "quiet", size: "icon" })}
        >
          <SquarePen aria-hidden="true" />
        </Link>
      </div>

      <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
        {conversations.data?.map((c) => (
          <li key={c.id}>
            <Link
              to="/c/$conversationId"
              params={{ conversationId: c.id }}
              onClick={onNavigate}
              className="block truncate rounded-lg px-3 py-2.5 text-ink hover:bg-surface-sunken"
              activeProps={{ className: "bg-accent-soft font-medium", "aria-current": "page" }}
            >
              {c.title}
            </Link>
          </li>
        ))}
        {conversations.data?.length === 0 && (
          <li className="px-3 py-2.5 text-sm text-ink-muted">Aucune conversation pour l'instant.</li>
        )}
      </ul>

      <div className="flex shrink-0 items-center gap-2 border-t border-line px-4 py-3">
        <span className="min-w-0 flex-1 truncate text-sm text-ink-muted">{me.data?.email}</span>
        <Button variant="quiet" size="sm" onClick={() => void signOut()}>
          <LogOut aria-hidden="true" />
          Se déconnecter
        </Button>
      </div>
    </nav>
  );
}
