"""Genere les icones de l'application installee a partir de la geometrie du monogramme.

    python3 scripts/make-icons.py      (necessite Pillow ; sortie dans public/icons/)

Meme dessin que src/components/Monogram.tsx (repere de 32 unites) : carre arrondi
vert-de-gris (rayon 9) et un L (x 11 a 22, y 8,5 a 24, epaisseur 3,6). Les icones
« maskable » remplissent tout le carre et gardent le L dans la zone sure (80 % centraux),
car Android y applique sa propre forme (cercle, goutte...).
"""

from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = "#287363"
INK = "#FFFFFF"
OUT = Path(__file__).resolve().parents[1] / "public" / "icons"
L_SHAPE = [(11, 8.5), (14.6, 8.5), (14.6, 20.7), (22, 20.7), (22, 24), (11, 24)]


def draw(size: int, maskable: bool) -> Image.Image:
    scale = 4  # sur-echantillonnage pour des bords nets
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    unit = big / 32
    if maskable:
        pen.rectangle([0, 0, big, big], fill=ACCENT)
        # Le L, centre exactement et agrandi, reste dans la zone sure (cercle de rayon 40 %).
        factor = 0.85
        cx = (min(x for x, _ in L_SHAPE) + max(x for x, _ in L_SHAPE)) / 2
        cy = (min(y for _, y in L_SHAPE) + max(y for _, y in L_SHAPE)) / 2
        points = [
            ((x - cx) * unit * factor + big / 2, (y - cy) * unit * factor + big / 2)
            for x, y in L_SHAPE
        ]
    else:
        pen.rounded_rectangle([0, 0, big - 1, big - 1], radius=9 * unit, fill=ACCENT)
        points = [(x * unit, y * unit) for x, y in L_SHAPE]
    pen.polygon(points, fill=INK)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw(192, maskable=False).save(OUT / "icon-192.png", optimize=True)
    draw(512, maskable=False).save(OUT / "icon-512.png", optimize=True)
    draw(512, maskable=True).save(OUT / "icon-maskable-512.png", optimize=True)
    # iOS arrondit lui-meme les coins : fond plein, sans transparence.
    draw(180, maskable=True).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    (OUT / "icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        f'<rect width="32" height="32" rx="9" fill="{ACCENT}"/>'
        f'<path d="M11 8.5h3.6v12.2H22V24H11z" fill="{INK}"/></svg>\n',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
