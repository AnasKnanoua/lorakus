/** Regroupe des elements par anciennete, comme une liste de conversations (Aujourd'hui, Hier...). */
export const RECENCY_GROUPS = ["Aujourd'hui", "Hier", "7 derniers jours", "30 derniers jours", "Plus ancien"] as const;
export type RecencyGroup = (typeof RECENCY_GROUPS)[number];

export function recencyGroup(iso: string, now: Date = new Date()): RecencyGroup {
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const at = new Date(iso).getTime();
  const DAY = 86_400_000;
  if (at >= day) return "Aujourd'hui";
  if (at >= day - DAY) return "Hier";
  if (at >= day - 7 * DAY) return "7 derniers jours";
  if (at >= day - 30 * DAY) return "30 derniers jours";
  return "Plus ancien";
}

export function groupByRecency<T>(items: readonly T[], date: (item: T) => string, now = new Date()) {
  const groups = new Map<RecencyGroup, T[]>();
  for (const item of items) {
    const key = recencyGroup(date(item), now);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return RECENCY_GROUPS.filter((g) => groups.has(g)).map((g) => ({ label: g, items: groups.get(g) ?? [] }));
}
