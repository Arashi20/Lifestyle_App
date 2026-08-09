"""
Generates the app's favicon/home-screen icon set from a simple "AMB"
monogram, matching the site's sage/cream palette and using Georgia (the
CSS serif fallback for Fraunces) since Fraunces itself is a webfont with
no local .ttf to render with. Re-run after changing COLORS/TEXT below.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG_COLOR = "#A3AE8E"  # sage accent
TEXT_COLOR = "#FBF6F0"  # cream
TEXT = "AMB"
FONT_PATH = "C:/Windows/Fonts/georgiab.ttf"  # Georgia Bold

STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "static"
SUPERSAMPLE = 1024


def render_icon(size: int) -> Image.Image:
    img = Image.new("RGB", (SUPERSAMPLE, SUPERSAMPLE), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Shrink the font until the text fits comfortably within ~70% of the
    # canvas width, leaving safe padding for OS-applied rounded-corner masks.
    max_width = SUPERSAMPLE * 0.7
    font_size = int(SUPERSAMPLE * 0.4)
    while font_size > 10:
        font = ImageFont.truetype(FONT_PATH, font_size)
        bbox = draw.textbbox((0, 0), TEXT, font=font)
        if bbox[2] - bbox[0] <= max_width:
            break
        font_size -= 8

    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    position = ((SUPERSAMPLE - text_w) / 2 - bbox[0], (SUPERSAMPLE - text_h) / 2 - bbox[1])
    draw.text(position, TEXT, font=font, fill=TEXT_COLOR)
    return img.resize((size, size), Image.LANCZOS)


def main():
    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    render_icon(180).save(STATIC_DIR / "apple-touch-icon.png")
    render_icon(192).save(STATIC_DIR / "icon-192.png")
    render_icon(512).save(STATIC_DIR / "icon-512.png")
    render_icon(32).save(STATIC_DIR / "favicon-32.png")
    render_icon(16).save(STATIC_DIR / "favicon-16.png")

    ico_sizes = [(16, 16), (32, 32), (48, 48)]
    render_icon(48).save(STATIC_DIR / "favicon.ico", sizes=ico_sizes)

    print(f"Icons written to {STATIC_DIR}")


if __name__ == "__main__":
    main()
