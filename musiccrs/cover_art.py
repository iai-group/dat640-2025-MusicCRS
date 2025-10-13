from __future__ import annotations
import hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import io
import base64
import requests
from typing import Optional

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


def _fetch_album_image(url: str, size: int = 640) -> Optional[Image.Image]:
    """Fetch and resize album artwork from Spotify."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        img = Image.open(io.BytesIO(response.content))
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        return img
    except Exception as e:
        print(f"Error fetching album image: {e}")
        return None


def _create_spotify_style_cover(album_images: list[Image.Image], size: int = 640) -> Image.Image:
    """
    Create Spotify-style playlist cover based on number of album images.
    - 1 image: full size
    - 2 images: split vertically 50/50
    - 3 images: top 50% one image, bottom 50% split horizontally
    - 4+ images: 2x2 grid using first 4
    """
    canvas = Image.new("RGB", (size, size), (30, 30, 30))
    
    num_images = len(album_images)
    
    if num_images == 0:
        return canvas
    
    elif num_images == 1:
        # Single image fills entire cover
        canvas.paste(album_images[0].resize((size, size), Image.Resampling.LANCZOS), (0, 0))
    
    elif num_images == 2:
        # Two images split vertically
        half = size // 2
        canvas.paste(album_images[0].resize((half, size), Image.Resampling.LANCZOS), (0, 0))
        canvas.paste(album_images[1].resize((half, size), Image.Resampling.LANCZOS), (half, 0))
    
    elif num_images == 3:
        # Top: one image (50%)
        # Bottom: two images (25% each)
        half = size // 2
        canvas.paste(album_images[0].resize((size, half), Image.Resampling.LANCZOS), (0, 0))
        canvas.paste(album_images[1].resize((half, half), Image.Resampling.LANCZOS), (0, half))
        canvas.paste(album_images[2].resize((half, half), Image.Resampling.LANCZOS), (half, half))
    
    else:  # 4 or more images
        # 2x2 grid using first 4 images
        half = size // 2
        canvas.paste(album_images[0].resize((half, half), Image.Resampling.LANCZOS), (0, 0))
        canvas.paste(album_images[1].resize((half, half), Image.Resampling.LANCZOS), (half, 0))
        canvas.paste(album_images[2].resize((half, half), Image.Resampling.LANCZOS), (0, half))
        canvas.paste(album_images[3].resize((half, half), Image.Resampling.LANCZOS), (half, half))
    
    return canvas


def _create_fallback_cover(playlist, size: int = 640) -> Image.Image:
    """Create a fallback mosaic cover when album images aren't available."""
    seed = playlist.name + "|" + "|".join([t.artist + ":" + t.title for t in playlist.tracks[:8]])
    colors = _hash_colors(seed, 9)

    tile = size // 3
    img = Image.new("RGB", (size, size), (30, 30, 30))
    draw = ImageDraw.Draw(img)

    # 3x3 mosaic
    idx = 0
    for y in range(3):
        for x in range(3):
            draw.rectangle((x * tile, y * tile, (x + 1) * tile, (y + 1) * tile), fill=colors[idx % len(colors)])
            idx += 1
    
    return img


def generate_cover(user_id: str, playlist) -> str:
    """
    Create a Spotify-style playlist cover using album artwork.
    Falls back to color mosaic if Spotify images unavailable.
    Returns a data URL.
    """
    size = 640
    
    # Try to get album images from Spotify for first 4 tracks
    from .spotify_api import get_spotify_api
    
    album_images = []
    spotify = get_spotify_api()
    
    if spotify and len(playlist.tracks) > 0:
        # Get album artwork for first 4 unique tracks
        seen_albums = set()
        for track in playlist.tracks[:8]:  # Check up to 8 tracks to get 4 unique albums
            if len(album_images) >= 4:
                break
            
            details = spotify.get_track_details(track.artist, track.title)
            if details and details.get("album_image"):
                album_url = details["album_image"]
                # Avoid duplicate albums
                if album_url not in seen_albums:
                    seen_albums.add(album_url)
                    img = _fetch_album_image(album_url, size)
                    if img:
                        album_images.append(img)
    
    # Create cover based on available images
    if album_images:
        img = _create_spotify_style_cover(album_images, size)
    else:
        # Fallback to color mosaic
        img = _create_fallback_cover(playlist, size)
    
    # No text overlay - the album artwork grid is the cover
    # This satisfies R2.6 as the cover is based on playlist songs

    # Convert to RGB for saving
    img = img.convert("RGB")

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
