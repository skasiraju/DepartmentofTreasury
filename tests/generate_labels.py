"""
Generates synthetic test label images using Pillow.
Images are simple but contain the same regulatory text a real label would have,
so the vision model can read and extract them.

Usage:
    pip install Pillow
    python tests/generate_labels.py

Images are saved to tests/fixtures/images/.
Pair each image with the corresponding JSON in tests/fixtures/ for manual testing.
"""
from __future__ import annotations
import os
import sys
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).parent / "fixtures" / "images"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TTB_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = []
    if sys.platform == "win32":
        win_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        candidates = [
            os.path.join(win_fonts, "arial.ttf"),
            os.path.join(win_fonts, "calibri.ttf"),
            os.path.join(win_fonts, "segoeui.ttf"),
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue

    # Pillow >= 10.1 supports a size argument on the built-in bitmap font
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_label(
    filename: str,
    brand_name: str,
    class_type: str,
    alcohol_content: str,
    net_contents: str,
    bottler_info: str,
    warning_text: str | None = None,
    country_of_origin: str | None = None,
) -> Path:
    """
    Creates a simple label image with the given regulatory fields.
    Pass warning_text="" to omit the government warning entirely (test the rejection case).
    """
    width, height = 520, 720
    bg_color = "#f7f2e8"
    border_color = "#7a5c1e"
    text_dark = "#1a1a1a"
    text_mid = "#444444"

    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    font_title  = _load_font(30)
    font_main   = _load_font(19)
    font_small  = _load_font(13)

    # Outer border
    draw.rectangle([12, 12, width - 12, height - 12], outline=border_color, width=3)
    # Inner border
    draw.rectangle([18, 18, width - 18, height - 18], outline=border_color, width=1)

    y = 44
    margin = 36

    def draw_centered(text: str, font: ImageFont.FreeTypeFont, color: str = text_dark) -> None:
        nonlocal y
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), text, fill=color, font=font)
        y += (bbox[3] - bbox[1]) + 10

    def draw_left(text: str, font: ImageFont.FreeTypeFont, color: str = text_mid) -> None:
        nonlocal y
        draw.text((margin, y), text, fill=color, font=font)
        bbox = draw.textbbox((0, 0), text, font=font)
        y += (bbox[3] - bbox[1]) + 8

    def draw_divider(gap_before: int = 10, gap_after: int = 10) -> None:
        nonlocal y
        y += gap_before
        draw.line([margin, y, width - margin, y], fill="#b8a070", width=1)
        y += gap_after

    draw_centered(brand_name, font_title)
    draw_centered(class_type, font_main, color=text_mid)
    draw_divider(gap_before=6)
    draw_centered(alcohol_content, font_main)
    draw_centered(net_contents, font_main)

    if country_of_origin:
        draw_divider()
        draw_centered(f"Product of {country_of_origin}", font_small, color=text_mid)

    draw_divider()

    for part in bottler_info.split(","):
        draw_left(part.strip(), font_small)

    draw_divider()

    # Government warning — wrap to fit within label width
    actual_warning = warning_text if warning_text is not None else TTB_WARNING
    if actual_warning:
        char_width = width // 8  # approximate chars per line at font_small size
        for line in textwrap.wrap(actual_warning, width=char_width):
            draw_left(line, font_small, color=text_dark)

    out_path = OUTPUT_DIR / filename
    img.save(out_path, quality=95)
    print(f"  created  {out_path.name}")
    return out_path


if __name__ == "__main__":
    print("Generating test label images...\n")

    # All fields correct — should PASS
    make_label(
        "bourbon_pass.jpg",
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        bottler_info="Old Tom Distillery, Lexington, KY 40511",
    )

    # Wrong ABV on label — should FAIL on alcohol_content
    make_label(
        "bourbon_wrong_abv.jpg",
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="46% Alc./Vol. (92 Proof)",
        net_contents="750 mL",
        bottler_info="Old Tom Distillery, Lexington, KY 40511",
    )

    # Import wine with country of origin — should PASS
    make_label(
        "wine_import_pass.jpg",
        brand_name="Château Bordeaux Reserve",
        class_type="Red Wine",
        alcohol_content="13.5% Alc./Vol.",
        net_contents="750 mL",
        bottler_info="Imported by Prestige Imports, New York, NY 10001",
        country_of_origin="France",
    )

    # Warning with lowercase prefix — should FAIL on government_warning
    make_label(
        "bourbon_warning_lowercase.jpg",
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        bottler_info="Old Tom Distillery, Lexington, KY 40511",
        warning_text=TTB_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:"),
    )

    # No warning at all — should FAIL on government_warning
    make_label(
        "bourbon_no_warning.jpg",
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        bottler_info="Old Tom Distillery, Lexington, KY 40511",
        warning_text="",
    )

    print(f"\nDone. Images saved to: {OUTPUT_DIR}")
    print("Run unit tests with:  pytest tests/test_verifier.py -v")
