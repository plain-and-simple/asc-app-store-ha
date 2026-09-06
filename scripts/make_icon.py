"""Render the App Store Connect for Home Assistant brand icon.

A rounded iOS-blue tile with a download arrow — first-time App Units are the
point of the integration. Drawn at 4x and downsampled so edges stay clean.
"""

from pathlib import Path

from PIL import Image, ImageDraw

S = 4
W = 512
C = W * S

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "custom_components" / "asc_app_store" / "brand"

BG_TOP = (10, 132, 255)
BG_BOTTOM = (0, 64, 168)
ARROW = (255, 255, 255)


def s(*vals: float) -> tuple[int, ...]:
    """Scale logical coordinates up to the supersampled canvas."""
    return tuple(round(v * S) for v in vals)


def rounded_tile() -> Image.Image:
    """Return the background tile with a vertical gradient and rounded corners."""
    grad = Image.new("RGB", (1, C))
    for y in range(C):
        t = y / (C - 1)
        grad.putpixel(
            (0, y),
            tuple(
                round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM, strict=True)
            ),
        )
    tile = grad.resize((C, C)).convert("RGBA")

    mask = Image.new("L", (C, C), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, C - 1, C - 1], radius=112 * S, fill=255
    )
    tile.putalpha(mask)
    return tile


def draw_download(base: Image.Image) -> None:
    """A shaft, a chevron, and a tray — unmistakably 'download'."""
    d = ImageDraw.Draw(base)
    # Shaft
    d.rounded_rectangle(s(232, 120, 280, 300), radius=16 * S, fill=ARROW)
    # Chevron
    d.polygon([s(160, 250), s(256, 360), s(352, 250)], fill=ARROW)
    # Tray
    d.rounded_rectangle(s(150, 390, 362, 430), radius=16 * S, fill=ARROW)


def main() -> None:
    """Compose the icon and write both required sizes."""
    base = rounded_tile()
    draw_download(base)

    OUT.mkdir(parents=True, exist_ok=True)
    for size, name in ((512, "icon@2x.png"), (256, "icon.png")):
        base.resize((size, size), Image.LANCZOS).save(OUT / name)
        print(f"wrote {OUT / name} ({size}x{size})")


if __name__ == "__main__":
    main()
