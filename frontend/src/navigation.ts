import type { LucideIcon } from "lucide-react";
import { Brain, CalendarSync } from "lucide-react";

/**
 * Destinations de l'application, declarees ici et nulle part ailleurs (docs/frontend.md,
 * « Navigation »). La barre laterale les affiche par groupe :
 *
 * - "assistant" : ce que Lorakus sait et gere pour toi (Memoire ; puis Aujourd'hui, Taches,
 *   Agenda...). Toujours visible, quatre ou cinq entrees au plus.
 * - "tools" : services secondaires et modules (veille, finances, echecs...). Groupe repliable,
 *   absent tant qu'il est vide.
 *
 * Les reglages et le compte vivent dans le menu du profil, en bas : jamais dans la liste.
 * Une nouvelle fonctionnalite = une entree ici, sans toucher a la barre laterale.
 */
export type NavGroup = "assistant" | "tools";

export interface NavItem {
  id: string;
  label: string;
  to: "/memoire" | "/calendriers";
  icon: LucideIcon;
  group: NavGroup;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { id: "memory", label: "Mémoire", to: "/memoire", icon: Brain, group: "assistant" },
  { id: "calendars", label: "Calendriers", to: "/calendriers", icon: CalendarSync, group: "tools" },
];

export const NAV_GROUP_LABELS: Record<NavGroup, string> = {
  assistant: "Assistant",
  tools: "Outils",
};
