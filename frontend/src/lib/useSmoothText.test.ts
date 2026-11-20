import { describe, expect, it } from "vitest";

import { nextLength } from "./useSmoothText";

describe("nextLength", () => {
  it("avance d'au moins deux caracteres", () => {
    expect(nextLength(0, 4)).toBe(2); // 15 % de 4 arrondi donnerait 1
    expect(nextLength(9, 10)).toBe(10);
  });

  it("rattrape un grand retard par paliers de 15 %", () => {
    expect(nextLength(0, 1000)).toBe(150);
    expect(nextLength(500, 1000)).toBe(575);
  });

  it("ne depasse jamais le texte recu", () => {
    expect(nextLength(10, 10)).toBe(10);
    expect(nextLength(12, 10)).toBe(10);
    expect(nextLength(99, 100)).toBe(100);
  });

  it("rattrape tout retard en peu d'images", () => {
    let shown = 0;
    let frames = 0;
    while (shown < 2000) {
      shown = nextLength(shown, 2000);
      frames += 1;
    }
    expect(frames).toBeLessThan(60); // moins d'une seconde a 60 images par seconde
  });
});
