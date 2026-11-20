/**
 * Dates et durees d'une evaluation, ecrites en francais. « Aujourd'hui » n'est jamais calcule
 * ici : le nombre de jours restants vient du serveur (fuseau du compte).
 */

const DAY = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const DAY_WITH_YEAR = new Intl.DateTimeFormat("fr-FR", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});

/** « vendredi 20 novembre » (avec l'annee si ce n'est pas celle en cours). `iso` : AAAA-MM-JJ. */
export function longDate(iso: string, now: Date = new Date()): string {
  const [year = 0, month = 1, day = 1] = iso.slice(0, 10).split("-").map(Number);
  // Date construite en heure locale : une date ISO lue en UTC reculerait d'un jour a l'ouest.
  const date = new Date(year, month - 1, day);
  return (year === now.getFullYear() ? DAY : DAY_WITH_YEAR).format(date);
}

/** « aujourd'hui », « demain », « dans 3 jours », « hier », « il y a 2 jours ». */
export function relativeDay(daysLeft: number): string {
  if (daysLeft === 0) return "aujourd'hui";
  if (daysLeft === 1) return "demain";
  if (daysLeft === -1) return "hier";
  return daysLeft > 1 ? `dans ${String(daysLeft)} jours` : `il y a ${String(-daysLeft)} jours`;
}

/** « 45 min », « 3 h », « 1 h 30 » (comme les cartes du chat). */
export function duration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${String(rest)} min`;
  return rest === 0 ? `${String(hours)} h` : `${String(hours)} h ${String(rest).padStart(2, "0")}`;
}

/** « 2 », « 0,5 » : virgule francaise. */
export function weight(value: number): string {
  return String(value).replace(".", ",");
}

/** Heures saisies (« 1,5 », « 3 ») vers des minutes entieres ; null si vide ou invalide. */
export function hoursToMinutes(text: string): number | null {
  const value = Number(text.trim().replace(",", "."));
  if (text.trim() === "" || !Number.isFinite(value) || value <= 0) return null;
  return Math.max(1, Math.round(value * 60));
}

/** Minutes vers la valeur du champ « heures » (« 1,5 »). */
export function minutesToHours(minutes: number | null): string {
  return minutes === null ? "" : weight(Math.round((minutes / 60) * 100) / 100);
}
