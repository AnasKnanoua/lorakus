import { describe, expect, it } from "vitest";

import { groupByRecency, recencyGroup } from "./dates";

const NOW = new Date(2026, 10, 13, 15, 0);

describe("anciennete", () => {
  it("classe une date dans le bon groupe", () => {
    expect(recencyGroup(new Date(2026, 10, 13, 0, 5).toISOString(), NOW)).toBe("Aujourd'hui");
    expect(recencyGroup(new Date(2026, 10, 12, 23, 59).toISOString(), NOW)).toBe("Hier");
    expect(recencyGroup(new Date(2026, 10, 8).toISOString(), NOW)).toBe("7 derniers jours");
    expect(recencyGroup(new Date(2026, 9, 20).toISOString(), NOW)).toBe("30 derniers jours");
    expect(recencyGroup(new Date(2025, 0, 1).toISOString(), NOW)).toBe("Plus ancien");
  });

  it("garde l'ordre des groupes et des elements, sans groupe vide", () => {
    const items = [new Date(2026, 10, 13, 9), new Date(2025, 0, 1), new Date(2026, 10, 13, 8)].map((d) =>
      d.toISOString(),
    );
    expect(groupByRecency(items, (d) => d, NOW).map((g) => [g.label, g.items.length])).toEqual([
      ["Aujourd'hui", 2],
      ["Plus ancien", 1],
    ]);
  });
});
