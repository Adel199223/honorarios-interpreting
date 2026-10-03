"""Read selected original photos from one explicitly configured local folder.

This module neither discovers devices nor writes files. Listing reads directory
metadata only; a separate, fingerprint-bound action reads one selected original.
Upload, source review and all provider decisions stay in the existing workflow.
"""
from __future__ import annotations

import hashlib
import hmac
from collections import OrderedDict
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
from threading import Lock
from typing import Any
import unicodedata
import warnings

from PIL import Image, ImageOps, JpegImagePlugin


MAX_CAMERA_FILE_BYTES = 25 * 1024 * 1024
MAX_CAMERA_SCAN_ENTRIES = 5000
MAX_CAMERA_PAGE_SIZE = 50
MAX_CAMERA_CONFIG_BYTES = 64 * 1024
MAX_CAMERA_THUMBNAIL_EDGE = 480
MAX_CAMERA_THUMBNAIL_SOURCE_PIXELS = 80_000_000
MAX_CAMERA_THUMBNAIL_JPEG_SOURCE_PIXELS = 250_000_000
MAX_CAMERA_THUMBNAIL_DECODE_PIXELS = 16_000_000
MAX_CAMERA_THUMBNAIL_BYTES = 512 * 1024
MAX_CAMERA_THUMBNAIL_CACHE_ENTRIES = 96
MAX_CAMERA_THUMBNAIL_CACHE_BYTES = 8 * 1024 * 1024
CAMERA_LABEL = "Camera"
_MIME_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
_UNAVAILABLE = "Camera is unavailable. Connect your phone and open Camera again, or use Choose another file."
_CHANGED = "The photo changed since Camera was loaded. Open Camera again and select it again."
_PREVIEW_UNAVAILABLE = "This photo preview is unavailable. You can still select the original photo."
# One decoder at a time bounds memory and phone reads even across multiple tabs.
# Only small, metadata-free JPEG bytes are retained; original photos never are.
_thumbnail_lock = Lock()
_thumbnail_cache: OrderedDict[tuple, bytes] = OrderedDict()


class CameraFolderError(ValueError):
    """An unavailable or invalid selection, safe to display without local paths."""


def _configured_folder(config_path: str | Path) -> Path | None:
    path = Path(config_path)
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_CAMERA_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CameraFolderError("The Camera setting cannot be read. Use Choose another file until it is repaired.") from exc
    if len(raw) > MAX_CAMERA_CONFIG_BYTES:
        raise CameraFolderError("The Camera setting is invalid. Use Choose another file until it is repaired.")
    try:
        config = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise CameraFolderError("The Camera setting is invalid. Use Choose another file until it is repaired.") from exc
    if not isinstance(config, dict):
        raise CameraFolderError("The Camera setting is invalid. Use Choose another file until it is repaired.")
    folder = config.get("camera_folder")
    if folder is None or folder == "":
        return None
    if not isinstance(folder, str) or not folder.strip() or "\x00" in folder:
        raise CameraFolderError("The Camera setting must name an absolute folder. Use Choose another file until it is repaired.")
    root = Path(folder)
    if not root.is_absolute():
        raise CameraFolderError("The Camera setting must name an absolute folder. Use Choose another file until it is repaired.")
    return root


def camera_folder_status(config_path: str | Path) -> dict[str, Any]:
    """Report saved setup without scanning the phone or exposing its path."""
    configured = _configured_folder(config_path) is not None
    return {"configured": configured, "label": CAMERA_LABEL if configured else ""}


def _camera_root(config_path: str | Path) -> Path:
    configured = _configured_folder(config_path)
    if configured is None:
        raise CameraFolderError("Camera is not configured. Use Choose another file to select a source.")
    try:
        if configured.is_symlink():
            raise CameraFolderError("The Camera setting must name a regular folder, not a link.")
        root = configured.resolve(strict=True)
        if not root.is_dir():
            raise CameraFolderError(_UNAVAILABLE)
        return root
    except OSError as exc:
        raise CameraFolderError(_UNAVAILABLE) from exc
    except RuntimeError as exc:
        raise CameraFolderError("The Camera setting must name a regular folder, not a link.") from exc


def _search_text(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", value).casefold() if char.isalnum())


def _fingerprint(root: Path, name: str, info: os.stat_result) -> str:
    identity = [os.path.normcase(str(root)), name, info.st_size, info.st_mtime_ns]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _safe_name(name: Any) -> str:
    if (not isinstance(name, str) or not name or len(name) > 255
            or name in {".", ".."} or name != name.strip()
            or any(char in name for char in ("/", "\\", ":", "\x00"))
            or any(ord(char) < 32 for char in name)
            or Path(name).is_absolute() or Path(name).name != name):
        raise CameraFolderError("Choose a listed Camera photo.")
    if Path(name).suffix.lower() not in _MIME_TYPES:
        raise CameraFolderError("Camera accepts original JPG, JPEG or PNG photos. Use Choose another file for a different source.")
    return name


def _selected_info(root: Path, name: str) -> tuple[Path, os.stat_result]:
    path = root / name
    try:
        info = path.stat(follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise CameraFolderError("Choose a regular Camera photo, not a folder or link.")
        if path.resolve(strict=True).parent != root:
            raise CameraFolderError("Choose a photo inside the configured Camera folder.")
        if info.st_size <= 0 or info.st_size > MAX_CAMERA_FILE_BYTES:
            raise CameraFolderError("Choose a nonempty Camera photo no larger than 25 MiB.")
        return path, info
    except (OSError, RuntimeError) as exc:
        raise CameraFolderError("The Camera photo is unavailable. Open Camera again and select it again.") from exc


def list_camera_files(
    config_path: str | Path, query: str = "", offset: int = 0, limit: int = 50,
) -> dict[str, Any]:
    """List bounded, immediate image entries without opening photo contents."""
    if not isinstance(query, str) or len(query) > 160:
        raise CameraFolderError("Search Camera with a filename or date of up to 160 characters.")
    if type(offset) is not int or offset < 0 or offset > MAX_CAMERA_SCAN_ENTRIES:
        raise CameraFolderError("Open Camera again to choose a valid page.")
    if type(limit) is not int or not 1 <= limit <= MAX_CAMERA_PAGE_SIZE:
        raise CameraFolderError("A Camera page can contain between 1 and 50 photos.")
    root = _camera_root(config_path)
    search = _search_text(query)
    items: list[dict[str, Any]] = []
    truncated = False
    try:
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_CAMERA_SCAN_ENTRIES:
                    truncated = True
                    break
                try:
                    name = _safe_name(entry.name)
                    if search and search not in _search_text(name):
                        continue
                    # lstat and resolution deliberately reject links, including
                    # links whose target happens to be inside the same folder.
                    _, info = _selected_info(root, name)
                except CameraFolderError:
                    continue
                items.append({"name": name, "size": info.st_size, "modified_ns": info.st_mtime_ns,
                              "fingerprint": _fingerprint(root, name, info)})
    except OSError as exc:
        raise CameraFolderError("Camera cannot be read. Check the phone connection and file access, then open Camera again.") from exc
    items.sort(key=lambda item: (item["name"].casefold(), item["name"]), reverse=True)
    total = len(items)
    end = offset + limit
    return {"configured": True, "label": CAMERA_LABEL, "items": items[offset:end], "total": total,
            "offset": offset, "limit": limit, "next_offset": end if end < total else None,
            "truncated": truncated}


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    # Fingerprints bind the listed metadata. Inode/device checks additionally
    # reject a replacement between validation and opening, even with same dates.
    return (left.st_dev, left.st_ino, left.st_mode, left.st_size, left.st_mtime_ns, left.st_ctime_ns) == (
        right.st_dev, right.st_ino, right.st_mode, right.st_size, right.st_mtime_ns, right.st_ctime_ns)


def _validated_selection(config_path: str | Path, name: str, fingerprint: str) -> tuple[Path, Path, os.stat_result]:
    name = _safe_name(name)
    if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise CameraFolderError("Open Camera again and select a listed photo.")
    root = _camera_root(config_path)
    path, before = _selected_info(root, name)
    if not hmac.compare_digest(_fingerprint(root, name, before), fingerprint):
        raise CameraFolderError(_CHANGED)
    return root, path, before


def read_camera_file(config_path: str | Path, name: str, fingerprint: str) -> tuple[bytes, str, str]:
    """Read one unchanged listed original; return (bytes, MIME type, filename)."""
    root, path, before = _validated_selection(config_path, name, fingerprint)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or not _same_file(before, opened):
                raise CameraFolderError(_CHANGED)
            content = handle.read(MAX_CAMERA_FILE_BYTES + 1)
            after_open = os.fstat(handle.fileno())
        _, after_path = _selected_info(root, name)
        if (not _same_file(opened, after_open) or not _same_file(before, after_path)
                or len(content) != before.st_size or len(content) > MAX_CAMERA_FILE_BYTES
                or not hmac.compare_digest(_fingerprint(root, name, after_path), fingerprint)
                or _camera_root(config_path) != root):
            raise CameraFolderError(_CHANGED)
    except OSError as exc:
        raise CameraFolderError("The Camera photo could not be read. Keep your phone connected, open Camera again and try again.") from exc
    return content, _MIME_TYPES[Path(name).suffix.lower()], name


def _jpeg_first_scan_is_interleaved(content: bytes, components: int) -> bool:
    """Read only JPEG marker headers; every frame component must share scan one."""
    offset = 2  # SOI was checked before selecting the JPEG parser.
    while offset < len(content):
        if content[offset] != 0xFF:
            return False
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        if offset >= len(content):
            return False
        marker = content[offset]
        offset += 1
        if marker == 0x01:  # TEM is the only standalone marker before scan one.
            continue
        if marker in {0x00, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7 or offset + 2 > len(content):
            return False
        length = int.from_bytes(content[offset:offset + 2], "big")
        if length < 2 or offset + length > len(content):
            return False
        if marker == 0xDA:
            return length == 6 + 2 * components and content[offset + 2] == components
        offset += length
    return False


def _thumbnail_jpeg(content: bytes) -> bytes:
    """Decode a bounded raster locally and encode only correctly oriented pixels."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            # JPEG headers can exceed Pillow's generic full-raster bomb limit
            # while libjpeg decodes only 1/64 of those pixels. Parse that format
            # directly, with our own hard cap, without changing global limits.
            opener = JpegImagePlugin.JpegImageFile if content.startswith(b"\xff\xd8\xff") else Image.open
            with opener(BytesIO(content)) as source:
                source_cap = MAX_CAMERA_THUMBNAIL_JPEG_SOURCE_PIXELS if source.format == "JPEG" else MAX_CAMERA_THUMBNAIL_SOURCE_PIXELS
                if source.format not in {"JPEG", "PNG"} or source.width * source.height > source_cap:
                    raise CameraFolderError(_PREVIEW_UNAVAILABLE)
                if source.format == "JPEG":
                    # Progressive/non-interleaved scans can retain full-size
                    # DCT coefficients even with reduced output. Large previews
                    # therefore require a sequential, all-component first scan.
                    if source.width * source.height > MAX_CAMERA_THUMBNAIL_DECODE_PIXELS and (
                        source.info.get("progressive") or source.info.get("progression")
                        or not _jpeg_first_scan_is_interleaved(content, source.layers)
                    ):
                        raise CameraFolderError(_PREVIEW_UNAVAILABLE)
                    # Request libjpeg's reduced decode before loading pixels.
                    source.draft("RGB", (MAX_CAMERA_THUMBNAIL_EDGE, MAX_CAMERA_THUMBNAIL_EDGE))
                if source.width * source.height > MAX_CAMERA_THUMBNAIL_DECODE_PIXELS:
                    raise CameraFolderError(_PREVIEW_UNAVAILABLE)
                source.thumbnail((MAX_CAMERA_THUMBNAIL_EDGE, MAX_CAMERA_THUMBNAIL_EDGE), Image.Resampling.LANCZOS, reducing_gap=2)
                with ImageOps.exif_transpose(source) as oriented:
                    # Fresh canvas strips EXIF/GPS, XMP, ICC and decoder info.
                    with Image.new("RGB", oriented.size, "white") as clean:
                        with oriented.convert("RGBA") as pixels:
                            clean.paste(pixels, mask=pixels.getchannel("A"))
                        output = BytesIO()
                        clean.save(output, format="JPEG", quality=78)
                        result = output.getvalue()
        if len(result) > MAX_CAMERA_THUMBNAIL_BYTES:
            raise CameraFolderError(_PREVIEW_UNAVAILABLE)
        return result
    except (OSError, ValueError, SyntaxError, MemoryError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise CameraFolderError(_PREVIEW_UNAVAILABLE) from exc


def _thumbnail_key(root: Path, name: str, fingerprint: str, info: os.stat_result) -> tuple:
    return (os.path.normcase(str(root)), name, fingerprint, info.st_dev, info.st_ino,
            info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_camera_thumbnail(config_path: str | Path, name: str, fingerprint: str) -> bytes:
    """Return a local preview, rechecking configured root and freshness on every hit."""
    with _thumbnail_lock:
        root, _, before = _validated_selection(config_path, name, fingerprint)
        key = _thumbnail_key(root, name, fingerprint, before)
        result = _thumbnail_cache.get(key)
        if result is None:
            # The original reader retains all descriptor/path/size race checks.
            content, _, _ = read_camera_file(config_path, name, fingerprint)
            result = _thumbnail_jpeg(content)
        after_root, _, after = _validated_selection(config_path, name, fingerprint)
        if after_root != root or not _same_file(before, after):
            raise CameraFolderError(_CHANGED)
        _thumbnail_cache[key] = result
        _thumbnail_cache.move_to_end(key)
        while (len(_thumbnail_cache) > MAX_CAMERA_THUMBNAIL_CACHE_ENTRIES
               or sum(len(value) for value in _thumbnail_cache.values()) > MAX_CAMERA_THUMBNAIL_CACHE_BYTES):
            _thumbnail_cache.popitem(last=False)
        return result
