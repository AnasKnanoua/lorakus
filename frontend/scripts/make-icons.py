"""Genere les icones de l'application installee : l'orbe de Lorakus sur fond encre de nuit.

    python3 scripts/make-icons.py      (necessite Pillow ; sortie dans public/icons/)

Meme dessin que l'orbe de l'interface (src/styles.css, .orb) : un coeur jade qui tire vers
le violet en bas a droite, un reflet en haut a gauche, un halo diffus. Les icones
« maskable » gardent l'orbe dans la zone sure (80 % centraux), car Android y applique sa
propre forme (cercle, goutte...).
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

NIGHT = (11, 14, 19)  # --background (theme sombre)
JADE = (79, 217, 189)  # --accent
VIOLET = (139, 123, 247)  # --violet
OUT = Path(__file__).resolve().parents[1] / "public" / "icons"


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t), round(a[2] + (b[2] - a[2]) * t))


def orb(diameter: int) -> Image.Image:
    """Sphere : degrade diagonal jade -> violet, ombre basse, reflet ; masque circulaire."""
    size = diameter
    sphere = Image.new("RGB", (size, size))
    pixels = sphere.load()
    assert pixels is not None
    cx = cy = (size - 1) / 2
    r = size / 2
    for y in range(size):
        for x in range(size):
            # Diagonale haut-gauche -> bas-droite, accentuee vers le bord.
            t = min(1.0, max(0.0, ((x - cx) + (y - cy)) / (2 * r) + 0.5))
            color = lerp(JADE, VIOLET, t**1.4)
            # Ombre : le bas de la sphere s'assombrit legerement.
            d = (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5) / r
            shade = 1 - 0.28 * max(0.0, d - 0.55) / 0.45 * (0.6 + 0.4 * (y / size))
            pixels[x, y] = tuple(max(0, min(255, round(c * shade))) for c in color)  # type: ignore[index]
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    # Reflet doux en haut a gauche.
    glint = Image.new("L", (size, size), 0)
    ImageDraw.Draw(glint).ellipse((size * 0.2, size * 0.14, size * 0.5, size * 0.4), fill=210)
    glint = glint.filter(ImageFilter.GaussianBlur(size * 0.07))
    sphere = Image.composite(Image.new("RGB", (size, size), (255, 255, 255)), sphere, glint)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(sphere, (0, 0), mask)
    return result


def draw(size: int, maskable: bool) -> Image.Image:
    scale = 2  # sur-echantillonnage pour des bords nets
    big = size * scale
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    background = Image.new("RGBA", (big, big), (*NIGHT, 255))
    if maskable:
        canvas = background
    else:
        corner = Image.new("L", (big, big), 0)
        ImageDraw.Draw(corner).rounded_rectangle((0, 0, big - 1, big - 1), radius=big * 0.23, fill=255)
        canvas.paste(background, (0, 0), corner)
    # L'orbe occupe 54 % (60 % dans la zone sure des icones maskable).
    d = round(big * (0.5 if maskable else 0.56))
    offset = (big - d) // 2
    # Halo : disque colore tres flou derriere l'orbe.
    halo = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    hd = round(d * 1.35)
    ImageDraw.Draw(halo).ellipse(
        ((big - hd) // 2, (big - hd) // 2, (big + hd) // 2, (big + hd) // 2), fill=(*JADE, 70)
    )
    halo = halo.filter(ImageFilter.GaussianBlur(big * 0.06))
    canvas = Image.alpha_composite(canvas, ImageChops.multiply(halo, Image.new("RGBA", (big, big), (255, 255, 255, 255))))
    canvas.alpha_composite(orb(d), (offset, offset))
    if not maskable:
        # Le halo ne deborde pas du carre arrondi.
        corner = Image.new("L", (big, big), 0)
        ImageDraw.Draw(corner).rounded_rectangle((0, 0, big - 1, big - 1), radius=big * 0.23, fill=255)
        canvas.putalpha(ImageChops.multiply(canvas.getchannel("A"), corner))
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<defs>
<radialGradient id="c" cx="40%" cy="40%" r="70%"><stop offset="0" stop-color="#4fd9bd"/><stop offset="1" stop-color="#8b7bf7"/></radialGradient>
<radialGradient id="g" cx="35%" cy="28%" r="25%"><stop offset="0" stop-color="#fff" stop-opacity=".85"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
</defs>
<rect width="32" height="32" rx="7.5" fill="#0b0e13"/>
<circle cx="16" cy="16" r="9" fill="url(#c)"/>
<circle cx="16" cy="16" r="9" fill="url(#g)"/>
</svg>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw(192, maskable=False).save(OUT / "icon-192.png", optimize=True)
    draw(512, maskable=False).save(OUT / "icon-512.png", optimize=True)
    draw(512, maskable=True).save(OUT / "icon-maskable-512.png", optimize=True)
    # iOS ignore la transparence : fond plein.
    draw(180, maskable=True).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    (OUT / "icon.svg").write_text(SVG)
    print("icones ecrites dans", OUT)


if __name__ == "__main__":
    main()
