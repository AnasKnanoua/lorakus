import type { LucideIcon } from "lucide-react";
import { Brain, CalendarSync, GraduationCap } from "lucide-react";

/**
 * Destinations de l'application, declarees ici et nulle part ailleurs (docs/frontend.md,
 * « Navigation »). La barre laterale les affiche par groupe :
 *
 * - "assistant" : ce que Lorakus sait et gere pour toi (Memoire ; puis Aujourd'hui, Taches,
 *   Agenda...). Toujours visible, quatre ou cinq entrees au plus.
 * - "tools" : services secondaires et modules (Cours, Calendriers ; puis veille, finances...). Affiches
 *   a plat sous l'assistant tant qu'ils sont peu nombreux : un groupe replie cachait chaque
 *   outil derriere un clic. Un regroupement reviendra si la liste depasse six entrees.
 *
 * Les reglages et le compte vivent dans le menu du profil, en bas : jamais dans la liste.
 * Une nouvelle fonctionnalite = une entree ici, sans toucher a la barre laterale.
 */
export type NavGroup = "assistant" | "tools";

export interface NavItem {
  id: string;
  label: string;
  to: "/memoire" | "/academic" | "/calendriers";
  icon: LucideIcon;
  group: NavGroup;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { id: "memory", label: "Mémoire", to: "/memoire", icon: Brain, group: "assistant" },
  { id: "academic", label: "Cours", to: "/academic", icon: GraduationCap, group: "tools" },
  { id: "calendars", label: "Calendriers", to: "/calendriers", icon: CalendarSync, group: "tools" },
];
