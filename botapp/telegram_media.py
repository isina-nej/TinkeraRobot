"""Download Telegram photos/stickers and normalize them for vision models.

Static stickers are WebP; animated/video stickers are converted via their
thumbnail (PhotoSize) when the full file cannot be decoded as a still image.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_IMAGE_EDGE = 1600
MAX_IMAGE_BYTES = 3_500_000
MAX_IMAGES = 3


def _pil():
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - exercised in deploy
        raise RuntimeError("Pillow is required for Noya vision (pip install Pillow)") from exc
    return Image, ImageOps


def normalize_image_bytes(raw: bytes, *, prefer_mime: str = "image/png") -> tuple[str, bytes]:
    """Return (mime, bytes) as a reasonably sized PNG/JPEG."""
    Image, ImageOps = _pil()
    with Image.open(io.BytesIO(raw)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        # Flatten transparency onto white for JPEG-friendly pipelines.
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        scale = min(1.0, MAX_IMAGE_EDGE / float(max(w, h, 1)))
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        # Prefer JPEG for photos (smaller); PNG only if caller insists and small.
        img.save(out, format="JPEG", quality=85, optimize=True)
        data = out.getvalue()
        if len(data) > MAX_IMAGE_BYTES:
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=70, optimize=True)
            data = out.getvalue()
        return "image/jpeg", data


def to_data_url(mime: str, data: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


async def _download_file_bytes(bot, file_id: str) -> bytes | None:
    try:
        file = await bot.get_file(file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        return buf.getvalue()
    except Exception:
        logger.exception("Failed to download Telegram file_id=%s", file_id)
        return None


def _largest_photo(message) -> Any | None:
    photos = getattr(message, "photo", None) or []
    if not photos:
        return None
    return max(photos, key=lambda p: int(getattr(p, "file_size", 0) or 0) or (
        int(getattr(p, "width", 0) or 0) * int(getattr(p, "height", 0) or 0)
    ))


async def image_bytes_from_photo_size(bot, photo_size) -> tuple[str, bytes] | None:
    raw = await _download_file_bytes(bot, photo_size.file_id)
    if not raw:
        return None
    try:
        return normalize_image_bytes(raw)
    except Exception:
        logger.exception("Failed to normalize photo")
        return None


async def image_bytes_from_sticker(bot, sticker) -> tuple[str, bytes] | None:
    """Convert a sticker to a still image (WebP/PNG/JPEG).

    Animated (.tgs) and video (.webm) stickers fall back to ``sticker.thumbnail``.
    """
    is_animated = bool(getattr(sticker, "is_animated", False))
    is_video = bool(getattr(sticker, "is_video", False))
    candidates: list[str] = []
    if not is_animated and not is_video:
        candidates.append(sticker.file_id)
    thumb = getattr(sticker, "thumbnail", None) or getattr(sticker, "thumb", None)
    if thumb is not None and getattr(thumb, "file_id", None):
        candidates.append(thumb.file_id)
    # Last resort: try the sticker file even if marked animated (some are still webp).
    if sticker.file_id not in candidates:
        candidates.append(sticker.file_id)

    for file_id in candidates:
        raw = await _download_file_bytes(bot, file_id)
        if not raw:
            continue
        try:
            return normalize_image_bytes(raw)
        except Exception:
            logger.debug("Sticker file_id=%s not decodable as still image", file_id, exc_info=True)
            continue
    return None


async def image_bytes_from_message(bot, message) -> tuple[str, bytes] | None:
    """Extract one image from a message (photo, sticker, or image document)."""
    if message is None:
        return None
    photo = _largest_photo(message)
    if photo is not None:
        return await image_bytes_from_photo_size(bot, photo)
    sticker = getattr(message, "sticker", None)
    if sticker is not None:
        return await image_bytes_from_sticker(bot, sticker)
    document = getattr(message, "document", None)
    if document is not None:
        mime = (getattr(document, "mime_type", None) or "").lower()
        if mime.startswith("image/"):
            raw = await _download_file_bytes(bot, document.file_id)
            if raw:
                try:
                    return normalize_image_bytes(raw)
                except Exception:
                    logger.exception("Failed to normalize image document")
    return None


async def collect_noya_images(bot, message, *, include_reply: bool = True) -> list[dict]:
    """Collect up to MAX_IMAGES normalized images for the vision API.

    Each item: ``{"mime": "image/jpeg", "data": b"...", "source": "message"|"reply"}``.
    """
    out: list[dict] = []
    seen: set[str] = set()

    async def _add(source: str, msg) -> None:
        if len(out) >= MAX_IMAGES or msg is None:
            return
        got = await image_bytes_from_message(bot, msg)
        if not got:
            return
        mime, data = got
        digest = f"{mime}:{len(data)}:{data[:64]!r}"
        if digest in seen:
            return
        seen.add(digest)
        out.append({"mime": mime, "data": data, "source": source})

    await _add("message", message)
    if include_reply:
        await _add("reply", getattr(message, "reply_to_message", None))
        # Parent of reply (one level) — useful when tagging on a reply chain.
        replied = getattr(message, "reply_to_message", None)
        if replied is not None:
            await _add("reply_parent", getattr(replied, "reply_to_message", None))
    return out


def images_to_data_urls(images: list[dict]) -> list[str]:
    return [to_data_url(img["mime"], img["data"]) for img in images if img.get("data")]
