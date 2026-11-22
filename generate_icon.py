"""Generate a high-DPI, anti-aliased Mouse + Energy Bolt Windows application icon (app.ico)."""

from pathlib import Path
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent


def make_app_icon(size: int = 512) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Outer dark rounded-square badge with cyan border
    pad = int(size * 0.04)
    radius = int(size * 0.22)
    border_w = int(size * 0.035)
    draw.rounded_rectangle(
        (pad, pad, size - pad, size - pad),
        radius=radius,
        fill="#0F1117",
        outline="#38BDF8",
        width=border_w,
    )

    # Subtle inner glow ring
    inner_pad = int(size * 0.095)
    draw.rounded_rectangle(
        (inner_pad, inner_pad, size - inner_pad, size - inner_pad),
        radius=int(size * 0.17),
        fill="#161B26",
        outline="#1E293B",
        width=int(size * 0.012),
    )

    # Stylized wireless mouse silhouette (centered slightly left to balance the bolt)
    mx1 = int(size * 0.24)
    my1 = int(size * 0.19)
    mx2 = int(size * 0.66)
    my2 = int(size * 0.81)
    mouse_w = mx2 - mx1
    mouse_radius = int(mouse_w * 0.48)

    # Mouse body
    draw.rounded_rectangle(
        (mx1, my1, mx2, my2),
        radius=mouse_radius,
        fill="#1F2937",
        outline="#E2E8F0",
        width=int(size * 0.028),
    )

    # Top button horizontal seam
    cx = (mx1 + mx2) // 2
    seam_y = int(my1 + (my2 - my1) * 0.36)
    draw.line((mx1 + int(size * 0.02), seam_y, mx2 - int(size * 0.02), seam_y), fill="#94A3B8", width=int(size * 0.016))
    # Vertical button divider
    draw.line((cx, my1 + int(size * 0.02), cx, seam_y), fill="#94A3B8", width=int(size * 0.016))

    # Scroll wheel pill
    sw_w = int(size * 0.045)
    sw_h = int(size * 0.12)
    sw_y1 = int(my1 + (my2 - my1) * 0.12)
    draw.rounded_rectangle(
        (cx - sw_w // 2, sw_y1, cx + sw_w // 2, sw_y1 + sw_h),
        radius=sw_w // 2,
        fill="#38BDF8",
    )

    # Energy / Lightning bolt badge in lower-right
    bx, by = int(size * 0.68), int(size * 0.66)
    br = int(size * 0.21)
    draw.ellipse(
        (bx - br, by - br, bx + br, by + br),
        fill="#0B1120",
        outline="#22C55E",
        width=int(size * 0.026),
    )

    # Crisp lightning bolt polygon inside badge
    bolt = [
        (bx + int(br * 0.12), by - int(br * 0.66)),
        (bx - int(br * 0.42), by + int(br * 0.06)),
        (bx - int(br * 0.04), by + int(br * 0.06)),
        (bx - int(br * 0.16), by + int(br * 0.66)),
        (bx + int(br * 0.44), by - int(br * 0.08)),
        (bx + int(br * 0.05), by - int(br * 0.08)),
    ]
    draw.polygon(bolt, fill="#22C55E")

    return img


if __name__ == "__main__":
    hi_res = make_app_icon(512)
    out_ico = BASE_DIR / "app.ico"
    out_png = BASE_DIR / "app_icon_preview.png"
    hi_res.save(out_png)
    hi_res.save(
        out_ico,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"Saved {out_ico} and {out_png}")
