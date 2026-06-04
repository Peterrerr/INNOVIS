"""Generate INNOVIS industrial camera icon and package as .icns for macOS."""
import math
import os
import subprocess
import tempfile
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIZE = 1024


def draw_icon(size=SIZE):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size

    # --- background rounded square ---
    pad = int(s * 0.06)
    r_bg = int(s * 0.22)
    bg_color = (28, 32, 38, 255)
    _rounded_rect(draw, pad, pad, s - pad, s - pad, r_bg, bg_color)

    # --- camera body (industrial box) ---
    bx1, by1 = int(s * 0.12), int(s * 0.28)
    bx2, by2 = int(s * 0.88), int(s * 0.72)
    body_r = int(s * 0.06)
    body_color = (52, 58, 68, 255)
    _rounded_rect(draw, bx1, by1, bx2, by2, body_r, body_color)

    # body highlight (top edge)
    _rounded_rect(draw, bx1, by1, bx2, by1 + int(s * 0.03), body_r, (80, 88, 100, 180))

    # --- lens housing (circle on left side) ---
    cx = int(s * 0.38)
    cy = int(s * 0.50)
    lens_r = int(s * 0.175)

    # outer ring (chrome)
    _circle(draw, cx, cy, lens_r, (130, 140, 155, 255))
    # ring bevel inner shadow
    _circle(draw, cx, cy, lens_r - int(s * 0.012), (40, 45, 52, 255))
    # glass outer
    _circle(draw, cx, cy, lens_r - int(s * 0.03), (20, 100, 180, 255))
    # glass mid
    _circle(draw, cx, cy, int(lens_r * 0.72), (10, 60, 140, 255))
    # glass core
    _circle(draw, cx, cy, int(lens_r * 0.46), (5, 30, 90, 255))
    # aperture blades hint
    for i in range(8):
        angle = math.radians(i * 45)
        ax = cx + int(math.cos(angle) * lens_r * 0.22)
        ay = cy + int(math.sin(angle) * lens_r * 0.22)
        draw.ellipse(
            [ax - int(s * 0.013), ay - int(s * 0.013),
             ax + int(s * 0.013), ay + int(s * 0.013)],
            fill=(15, 50, 110, 200),
        )
    # lens flare highlight
    hx = cx - int(lens_r * 0.32)
    hy = cy - int(lens_r * 0.32)
    hr = int(lens_r * 0.22)
    for step, alpha in [(0, 120), (1, 60), (2, 25)]:
        rr = hr - step * int(s * 0.012)
        if rr > 0:
            _circle_alpha(draw, hx, hy, rr, (220, 235, 255, alpha))

    # --- right panel: connector block ---
    px1, py1 = int(s * 0.70), int(s * 0.35)
    px2, py2 = int(s * 0.82), int(s * 0.65)
    _rounded_rect(draw, px1, py1, px2, py2, int(s * 0.02), (38, 44, 54, 255))
    # connector pins
    pin_x = int(s * 0.745)
    for row in range(3):
        for col in range(2):
            px = pin_x + col * int(s * 0.032)
            py = int(s * 0.415) + row * int(s * 0.055)
            draw.ellipse([px - int(s * 0.012), py - int(s * 0.012),
                          px + int(s * 0.012), py + int(s * 0.012)],
                         fill=(180, 160, 60, 255))

    # --- LED indicator ---
    led_x, led_y = int(s * 0.72), int(s * 0.315)
    led_r = int(s * 0.022)
    _circle(draw, led_x, led_y, led_r + int(s * 0.008), (0, 200, 80, 60))
    _circle(draw, led_x, led_y, led_r, (0, 230, 100, 255))
    _circle(draw, led_x - int(led_r * 0.3), led_y - int(led_r * 0.3),
            int(led_r * 0.4), (160, 255, 180, 200))

    # --- mounting screw holes (corners of body) ---
    screw_r = int(s * 0.018)
    screws = [
        (bx1 + int(s * 0.055), by1 + int(s * 0.055)),
        (bx1 + int(s * 0.055), by2 - int(s * 0.055)),
        (bx2 - int(s * 0.055), by1 + int(s * 0.055)),
        (bx2 - int(s * 0.055), by2 - int(s * 0.055)),
    ]
    for sx, sy in screws:
        _circle(draw, sx, sy, screw_r, (25, 30, 38, 255))
        _circle(draw, sx, sy, int(screw_r * 0.55), (70, 80, 95, 255))
        draw.line([sx - int(screw_r * 0.5), sy, sx + int(screw_r * 0.5), sy],
                  fill=(40, 48, 58, 255), width=max(1, int(s * 0.004)))

    # --- cable stub on right ---
    cable_x1 = bx2
    cable_y1 = int(s * 0.46)
    cable_y2 = int(s * 0.54)
    cable_x2 = bx2 + int(s * 0.05)
    draw.rectangle([cable_x1, cable_y1, cable_x2, cable_y2], fill=(22, 26, 32, 255))
    draw.rectangle([cable_x2, cable_y1 + int(s * 0.015),
                    cable_x2 + int(s * 0.015), cable_y2 - int(s * 0.015)],
                   fill=(60, 68, 80, 255))

    # --- INNOVIS text ---
    font_size = int(s * 0.072)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc",
                                        int(font_size * 0.38))
    except Exception:
        font = ImageFont.load_default()
        font_small = font

    text = "INNOVIS"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    tx = (s - tw) // 2 + int(s * 0.06)
    ty = int(s * 0.775)
    # shadow
    draw.text((tx + 2, ty + 2), text, font=font, fill=(0, 0, 0, 120))
    draw.text((tx, ty), text, font=font, fill=(200, 215, 235, 255))

    # tagline
    tag = "MACHINE VISION"
    tbbox = draw.textbbox((0, 0), tag, font=font_small)
    ttx = (s - (tbbox[2] - tbbox[0])) // 2 + int(s * 0.06)
    draw.text((ttx, ty + int(font_size * 1.1)), tag, font=font_small,
              fill=(100, 130, 170, 200))

    return img


def _rounded_rect(draw, x1, y1, x2, y2, r, fill):
    r = min(r, (x2 - x1) // 2, (y2 - y1) // 2)
    if r <= 0:
        draw.rectangle([x1, y1, x2, y2], fill=fill)
        return
    draw.rectangle([x1 + r, y1, x2 - r, y2], fill=fill)
    draw.rectangle([x1, y1 + r, x2, y2 - r], fill=fill)
    for cx, cy in [(x1 + r, y1 + r), (x2 - r, y1 + r),
                   (x1 + r, y2 - r), (x2 - r, y2 - r)]:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def _circle(draw, cx, cy, r, fill):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def _circle_alpha(draw, cx, cy, r, fill):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def build_icns(png_path, icns_path):
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "INNOVIS.iconset")
        os.makedirs(iconset)
        img = Image.open(png_path)
        specs = [
            (16, "16x16"), (32, "16x16@2x"),
            (32, "32x32"), (64, "32x32@2x"),
            (128, "128x128"), (256, "128x128@2x"),
            (256, "256x256"), (512, "256x256@2x"),
            (512, "512x512"), (1024, "512x512@2x"),
        ]
        for px, name in specs:
            resized = img.resize((px, px), Image.LANCZOS)
            resized.save(os.path.join(iconset, f"icon_{name}.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns_path], check=True)
    print(f"Saved: {icns_path}")


if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "..", "assets")
    os.makedirs(out_dir, exist_ok=True)

    png_path = os.path.join(out_dir, "icon.png")
    icns_path = os.path.join(out_dir, "icon.icns")

    icon = draw_icon()
    icon.save(png_path)
    print(f"Saved: {png_path}")

    build_icns(png_path, icns_path)
    print("Done. Use assets/icon.icns with PyInstaller.")
