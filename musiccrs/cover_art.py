from __future__ import annotations
import hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import io
import base64

# Still save a copy under project/static/covers for debugging,
# but we RETURN a data URL so the frontend doesn't depend on Flask static.
COVERS_DIR = (Path(__file__).resolve().parents[1] / "static" / "covers")
COVERS_DIR.mkdir(parents=True, exist_ok=True)

def _hash_colors(seed: str, n: int = 9) -> list[tuple[int, int, int]]:
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    colors = []
    for i in range(n):
        chunk = h[i * 6 : (i + 1) * 6]
        if len(chunk) < 6:
            chunk = (chunk + h)[:6]
        r = int(chunk[0:2], 16)
        g = int(chunk[2:4], 16)
        b = int(chunk[4:6], 16)
        colors.append((r, g, b))
    return colors

def generate_cover(user_id: str, playlist) -> str:
    """Create a deterministic mosaic cover and return a **data URL**.
    Also saves a PNG copy under static/covers for debugging."""
    seed = playlist.name + "|" + "|".join([t.artist + ":" + t.title for t in playlist.tracks[:8]])
    colors = _hash_colors(seed, 9)

    size = 640
    tile = size // 3
    img = Image.new("RGB", (size, size), (30, 30, 30))
    draw = ImageDraw.Draw(img)

    # 3x3 mosaic
    idx = 0
    for y in range(3):
        for x in range(3):
            draw.rectangle((x * tile, y * tile, (x + 1) * tile, (y + 1) * tile), fill=colors[idx % len(colors)])
            idx += 1

    # bottom overlay + text
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rectangle((0, size - 180, size, size), fill=(0, 0, 0, 150))

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 44)
        small = ImageFont.truetype("DejaVuSans.ttf", 22)
    except Exception:
        font = None
        small = None

    title = (playlist.name or "playlist")[:40]
    subtitle = f"{len(playlist.tracks)} tracks"
    text_x = 20
    text_y = size - 150
    if font:
        odraw.text((text_x, text_y), title, fill=(255, 255, 255, 255), font=font)
        odraw.text((text_x, text_y + 60), subtitle, fill=(230, 230, 230, 255), font=small or font)
    else:
        odraw.text((text_x, text_y), title, fill=(255, 255, 255, 255))
        odraw.text((text_x, text_y + 60), subtitle, fill=(230, 230, 230, 255))

    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    # Save a file copy (optional debug)
    safe_user = "".join(c for c in (user_id or "user") if c.isalnum() or c in ("-", "_")).strip("_")
    safe_name = "".join(c for c in (playlist.name or "default") if c.isalnum() or c in ("-", "_")).strip("_")
    out_path = COVERS_DIR / f"{safe_user}__{safe_name}.png"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, format="PNG")
    except Exception:
        pass  # saving is best-effort

    # Return as data URL so the frontend can display without hitting Flask static
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"
