"""Export the existing Frame mark's geometric paths as installable PNG icons."""
from pathlib import Path
from PIL import Image, ImageDraw

DESTINATION = Path(__file__).resolve().parents[1] / 'static' / 'brand'


def icon(size, *, maskable=False, apple=False):
    scale = 32
    image = Image.new('RGBA', (64 * scale, 64 * scale), '#c3f26b' if maskable else '#111315' if apple else (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if not maskable:
        draw.rounded_rectangle((0, 0, 64 * scale - 1, 64 * scale - 1), radius=17 * scale, fill='#c3f26b')
    # Square-capped strokes from frame-mark.svg, within the maskable safe circle.
    for box in [(16, 15, 22, 49), (16, 15, 49, 21), (16, 28, 42, 34), (35, 43, 49, 49), (43, 35, 49, 49)]:
        draw.rectangle(tuple(value * scale for value in box), fill='#14170f')
    return image.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == '__main__':
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        icon(size).save(DESTINATION / f'icon-{size}.png')
    icon(512, maskable=True).save(DESTINATION / 'icon-maskable-512.png')
    icon(180, apple=True).convert('RGB').save(DESTINATION / 'apple-touch-icon.png')
