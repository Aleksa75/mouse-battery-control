"""
Automatic Mouse Model Icon Fetcher & Background Remover
- Fetches a model image from Wikimedia Commons (free, no API key) when a new mouse is detected
- Removes solid corner backgrounds via flood-fill and tightly crops to the mouse silhouette
- Caches locally in `<base_dir>/icons/<slug>.png` so each model is fetched only once
"""

from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path
from PIL import Image

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "MouseBatteryControl/2.2 (Windows Desktop App)"


def process_mouse_image(img: Image.Image, tolerance: int = 22) -> Image.Image:
    """Remove solid background from corners via flood-fill and tightly crop."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    if w < 4 or h < 4:
        return rgba

    px = rgba.load()
    # Check if corners are already transparent
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    if not all(px[cx, cy][3] == 0 for cx, cy in corners):
        bg = px[0, 0][:3]
        vis: set[tuple[int, int]] = set(corners)
        q: deque[tuple[int, int]] = deque(corners)
        while q:
            x, y = q.popleft()
            r, g, b, a = px[x, y]
            if a == 0 or (
                abs(r - bg[0]) <= tolerance
                and abs(g - bg[1]) <= tolerance
                and abs(b - bg[2]) <= tolerance
            ):
                px[x, y] = (r, g, b, 0)
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in vis:
                        vis.add((nx, ny))
                        q.append((nx, ny))

    bbox = rgba.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    rgba.thumbnail((256, 256), Image.LANCZOS)
    return rgba


def save_custom_icon(src_file: Path, dest_path: Path) -> bool:
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(src_file)
        cleaned = process_mouse_image(img)
        cleaned.save(dest_path, format="PNG")
        return True
    except Exception:
        return False


def fetch_mouse_icon_from_web(model_name: str, dest_path: Path) -> bool:
    """Query Wikimedia Commons for a clean image of the mouse model and cache it."""
    query = f"{model_name} mouse"
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",  # File namespace
            "gsrlimit": "6",
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": "256",
            "format": "json",
        }
    )
    try:
        req = urllib.request.Request(f"{WIKIMEDIA_API}?{params}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return False

        # Prefer PNG/JPEG thumbnails
        best_url = None
        for page in pages.values():
            infos = page.get("imageinfo", [])
            if not infos:
                continue
            info = infos[0]
            mime = str(info.get("mime", "")).lower()
            thumb = info.get("thumburl") or info.get("url")
            if not thumb:
                continue
            if "png" in mime:
                best_url = thumb
                break
            if ("jpeg" in mime or "jpg" in mime or "webp" in mime) and best_url is None:
                best_url = thumb

        if not best_url:
            return False

        img_req = urllib.request.Request(best_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(img_req, timeout=10) as img_resp:
            raw_bytes = img_resp.read()

        img = Image.open(io.BytesIO(raw_bytes))
        cleaned = process_mouse_image(img)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned.save(dest_path, format="PNG")
        return True
    except Exception:
        return False
