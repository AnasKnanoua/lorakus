import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Outlet } from "@tanstack/react-router";
import { Menu } from "lucide-react";
import { useState } from "react";

import { AssistantDisabledError } from "@/api/assistant";
import { Button } from "@/components/ui/button";
import { conversationsQuery } from "@/lib/queries";

import { EnableAssistant } from "./EnableAssistant";
import { Sidebar } from "./Sidebar";

/**
 * Mise en page : sur grand ecran, la liste des conversations a gauche ; sur telephone, un
 * panneau qui s'ouvre depuis le bouton menu.
 */
export function ChatLayout() {
  const [open, setOpen] = useState(false);
  const conversations = useQuery(conversationsQuery);
  const disabled = conversations.error instanceof AssistantDisabledError;

  return (
    <div className="flex h-full">
      <aside className="hidden w-72 shrink-0 border-r border-line lg:block">
        <Sidebar />
      </aside>

      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-ink/40 lg:hidden" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed inset-y-0 left-0 w-[85%] max-w-xs pt-[env(safe-area-inset-top)] lg:hidden"
          >
            <Dialog.Title className="sr-only">Conversations</Dialog.Title>
            <Sidebar
              onNavigate={() => {
                setOpen(false);
              }}
            />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-14 shrink-0 items-center border-b border-line px-2 lg:hidden">
          <Button
            variant="quiet"
            size="icon"
            aria-label="Ouvrir la liste des conversations"
            onClick={() => {
              setOpen(true);
            }}
          >
            <Menu aria-hidden="true" />
          </Button>
          <span className="font-bold">Lorakus</span>
        </div>
        {disabled ? <EnableAssistant /> : <Outlet />}
      </main>
    </div>
  );
}
