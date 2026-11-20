import type { LucideIcon } from "lucide-react";
import { Brain, CalendarSync, GraduationCap, Sun } from "lucide-react";

/**
 * Destinations de l'application, declarees ici et nulle part ailleurs (docs/frontend.md,
 * « Navigation »). La barre laterale les affiche par groupe :
 *
 * - "assistant" : ce que Lorakus sait et gere pour toi (Ma journee, Memoire ; puis Taches,
 *   Agenda...). Toujours visible, quatre ou cinq entrees au plus. « Ma journee » et non
 *   « Aujourd'hui » : ce mot est deja le titre du premier groupe de conversations, juste
 *   en dessous.
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
  to: "/today" | "/memoire" | "/academic" | "/calendriers";
  icon: LucideIcon;
  group: NavGroup;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { id: "today", label: "Ma journée", to: "/today", icon: Sun, group: "assistant" },
  { id: "memory", label: "Mémoire", to: "/memoire", icon: Brain, group: "assistant" },
  { id: "academic", label: "Cours", to: "/academic", icon: GraduationCap, group: "tools" },
  { id: "calendars", label: "Calendriers", to: "/calendriers", icon: CalendarSync, group: "tools" },
];
