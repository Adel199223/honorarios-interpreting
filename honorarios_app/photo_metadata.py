"""Local photo metadata evidence; no provider calls or geographic inference.

Picker createTime is an instant, not a local calendar date:
https://developers.google.com/photos/picker/reference/rest/v1/mediaItems
IPTC LocationCreated is distinct from LocationShown and legacy City:
https://www.iptc.org/std/photometadata/documentation/userguide/
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import math
import re
import struct
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, IptcImagePlugin, JpegImagePlugin

from .camera_folder import (
    MAX_CAMERA_THUMBNAIL_DECODE_PIXELS,
    MAX_CAMERA_THUMBNAIL_EDGE,
    MAX_CAMERA_THUMBNAIL_JPEG_SOURCE_PIXELS,
    _jpeg_first_scan_is_interleaved,
)

_EXIF_IFD = 34665
_GPS_IFD = 34853
_IPTC_EXT = "http://iptc.org/std/Iptc4xmpExt/2008-02-29/"
_PHOTOSHOP = "http://ns.adobe.com/photoshop/1.0/"
_RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?P<fraction>\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})\Z")
_OFFSET = re.compile(r"([+-])(\d{2}):(\d{2})\Z")
_MAX_XMP_BYTES = 256 * 1024


class PhotoMetadataError(ValueError):
    """The supplied bytes cannot be read as an image."""


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return value.strip(" \t\r\n\x00") if isinstance(value, str) else ""


def _exif_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not re.fullmatch(r"\d{4}[:-]\d{2}[:-]\d{2} \d{2}:\d{2}:\d{2}", text):
        return None
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            pass
    return None


def _offset(value: Any) -> timezone | None:
    text = _text(value)
    match = _OFFSET.fullmatch(text)
    if not match or text == "-00:00":
        return None
    sign, hours, minutes = match.groups()
    if int(hours) > 23 or int(minutes) > 59:
        return None
    delta = timedelta(hours=int(hours), minutes=int(minutes))
    return timezone(-delta if sign == "-" else delta)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ifd(exif: Image.Exif, tag: int, warnings: list[str]) -> Mapping:
    try:
        result = exif.get_ifd(tag)
        return result if isinstance(result, Mapping) else {}
    except (KeyError, TypeError, ValueError, OSError, SyntaxError, IndexError, struct.error):
        warnings.append("Some embedded image metadata could not be read; check the original photo details.")
        return {}


def _number(value: Any) -> float:
    if isinstance(value, bool) or isinstance(value, (str, bytes)):
        raise ValueError("Not an EXIF rational number")
    if isinstance(value, (tuple, list)):
        if len(value) != 2:
            raise ValueError("Invalid rational")
        numerator, denominator = (_number(part) for part in value)
        if denominator == 0:
            raise ValueError("Zero denominator")
        result = numerator / denominator
    else:
        result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite number")
    return result


def extract_gps_coordinates(gps: Mapping[Any, Any]) -> dict[str, Any] | None:
    """Decode EXIF degrees/minutes/seconds. Invalid or incomplete GPS returns None.

    Coordinates are evidence only. They do not identify a city, venue or payer.
    Both hemisphere references are required; negative DMS values are invalid.
    """
    if not isinstance(gps, Mapping):
        return None
    try:
        values: list[float] = []
        for value_tag, ref_tag, maximum, refs in ((2, 1, 90, "NS"), (4, 3, 180, "EW")):
            reference = _text(gps.get(ref_tag)).upper()
            parts = gps.get(value_tag)
            if reference not in tuple(refs) or not isinstance(parts, (list, tuple)) or len(parts) != 3:
                return None
            degrees, minutes, seconds = (_number(value) for value in parts)
            if not (0 <= degrees <= maximum and 0 <= minutes < 60 and 0 <= seconds < 60):
                return None
            coordinate = degrees + minutes / 60 + seconds / 3600
            if coordinate > maximum:
                return None
            values.append(-coordinate if reference in "SW" else coordinate)
        return {"latitude": values[0], "longitude": values[1], "source": "exif_gps"}
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def _location_text(value: Any) -> str:
    value = _text(value)
    if not value or len(value) > 200 or any(ord(char) < 32 for char in value):
        return ""
    return " ".join(value.split())


def _embedded_locations(image: Image.Image, warnings: list[str]) -> list[dict[str, str]]:
    """Read named metadata locations without treating legacy/shown City as capture."""
    locations: list[dict[str, str]] = []

    def add(value: Any, source: str, scope: str) -> None:
        city = _location_text(value)
        candidate = {"city": city, "source": source, "scope": scope}
        if city and candidate not in locations and len(locations) < 20:
            locations.append(candidate)

    raw_xmp = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
    if raw_xmp:
        try:
            if isinstance(raw_xmp, str):
                raw_xmp = raw_xmp.encode("utf-8")
            if not isinstance(raw_xmp, bytes) or len(raw_xmp) > _MAX_XMP_BYTES:
                raise ValueError("Oversized XMP")
            # No DTD/entity expansion is needed for these simple metadata fields.
            if b"\x00" in raw_xmp or re.search(br"<!\s*(?:DOCTYPE|ENTITY)", raw_xmp, re.IGNORECASE):
                raise ValueError("Unsupported XMP declarations")
            root = ElementTree.fromstring(raw_xmp)
            for label, scope in (("LocationCreated", "capture"), ("LocationShown", "shown")):
                for location in root.iter(f"{{{_IPTC_EXT}}}{label}"):
                    for node in location.iter():
                        if node.tag == f"{{{_IPTC_EXT}}}City":
                            add(node.text, f"xmp_{label}", scope)
                        add(node.attrib.get(f"{{{_IPTC_EXT}}}City"), f"xmp_{label}", scope)
            for node in root.iter():
                if node.tag == f"{{{_PHOTOSHOP}}}City":
                    add(node.text, "xmp_photoshop_city", "unspecified")
                add(node.attrib.get(f"{{{_PHOTOSHOP}}}City"), "xmp_photoshop_city", "unspecified")
        except (ValueError, TypeError, ElementTree.ParseError, UnicodeError):
            warnings.append("Embedded XMP location metadata is unreadable or unsupported; no capture city was inferred.")
    try:
        iptc = IptcImagePlugin.getiptcinfo(image) or {}
        cities = iptc.get((2, 90), [])
        for value in cities if isinstance(cities, list) else [cities]:
            # Undeclared IIM encodings can be ambiguous; only accept UTF-8/ASCII.
            add(value, "iptc_legacy_city", "unspecified")
    except (OSError, ValueError, TypeError, IndexError, SyntaxError):
        warnings.append("Embedded IPTC location metadata could not be read.")
    return locations


def extract_photo_metadata(content: bytes) -> dict[str, Any]:
    """Extract JSON-safe metadata from the original bytes, preserving local day.

    Existing DateTimeDigitized fallback is retained with distinct provenance.
    DateTime (file modification) and GPSDateStamp never supply the capture date.
    Embedded locations/GPS are evidence, and no capture_city is synthesized.
    """
    try:
        # Metadata belongs to the original. A large sequential JPEG can be
        # validated using libjpeg's reduced decode, exactly as its Camera
        # preview is, without allocating a full 200 MP raster or changing
        # Pillow's process-wide bomb limit. Other formats keep their decoder
        # guards. The original content is never resized, encoded or replaced.
        opener = JpegImagePlugin.JpegImageFile if content.startswith(b"\xff\xd8\xff") else Image.open
        with opener(BytesIO(content)) as image:
            original_size = image.size
            if image.format == "JPEG":
                original_pixels = image.width * image.height
                if original_pixels > MAX_CAMERA_THUMBNAIL_JPEG_SOURCE_PIXELS:
                    raise PhotoMetadataError("The original photo exceeds the supported JPEG size.")
                if original_pixels > MAX_CAMERA_THUMBNAIL_DECODE_PIXELS and (
                    image.info.get("progressive") or image.info.get("progression")
                    or not _jpeg_first_scan_is_interleaved(content, image.layers)
                ):
                    raise PhotoMetadataError("This large JPEG cannot be decoded within the photo review limits.")
                image.draft("RGB", (MAX_CAMERA_THUMBNAIL_EDGE, MAX_CAMERA_THUMBNAIL_EDGE))
                if image.width * image.height > MAX_CAMERA_THUMBNAIL_DECODE_PIXELS:
                    raise PhotoMetadataError("This JPEG cannot be decoded within the photo review limits.")
            image.load()
            metadata: dict[str, Any] = {"width": original_size[0], "height": original_size[1], "format": image.format or ""}
            warnings: list[str] = []
            exif = image.getexif()
            capture = _ifd(exif, _EXIF_IFD, warnings)
            orientation = exif.get(274)
            if orientation not in (None, ""):
                try:
                    parsed_orientation = int(orientation)
                    if parsed_orientation not in range(1, 9):
                        raise ValueError("Invalid orientation")
                    metadata["exif_orientation"] = parsed_orientation
                    if parsed_orientation != 1:
                        warnings.append("Image has EXIF orientation metadata; verify the visible text direction before generating.")
                except (ValueError, TypeError, OverflowError):
                    warnings.append("Image has invalid EXIF orientation metadata; inspect its visible text direction.")
            for tag, offset_tag, source in ((36867, 36881, "DateTimeOriginal"), (36868, 36882, "DateTimeDigitized")):
                found = False
                for fields in (capture, exif):
                    raw = fields.get(tag)
                    captured = _exif_datetime(raw)
                    if captured is None:
                        if raw not in (None, "", b""):
                            warnings.append(f"EXIF {source} is invalid; it did not supply a capture date.")
                        continue
                    metadata.update(exif_date=captured.date().isoformat(), exif_date_source=source,
                                    exif_capture_time=captured.isoformat())
                    raw_offset = fields.get(offset_tag)
                    if raw_offset is None:
                        raw_offset = capture.get(offset_tag, exif.get(offset_tag))
                    if raw_offset not in (None, "", b""):
                        parsed_offset = _offset(raw_offset)
                        if parsed_offset is None:
                            warnings.append(f"EXIF offset for {source} is invalid or unknown; the local capture date was kept without inventing a UTC instant.")
                        else:
                            metadata["exif_utc_offset"] = _text(raw_offset)
                            try:
                                metadata["exif_capture_instant"] = _utc_text(captured.replace(tzinfo=parsed_offset))
                            except OverflowError:
                                warnings.append("The EXIF capture instant is outside the supported date range; check the photo date.")
                    found = True
                    break
                if found:
                    break
            if not metadata.get("exif_date") and _exif_datetime(exif.get(306)):
                warnings.append("The image has an EXIF modification date but no capture date. Confirm the actual photo/service date.")
            gps = _ifd(exif, _GPS_IFD, warnings)
            if gps:
                coordinates = extract_gps_coordinates(gps)
                if coordinates is None:
                    warnings.append("Embedded GPS coordinates are incomplete or invalid; confirm the capture location.")
                else:
                    metadata["gps_coordinates"] = coordinates
            locations = _embedded_locations(image, warnings)
            if locations:
                metadata["embedded_location_candidates"] = locations
                cities = {row["city"].casefold() for row in locations if row["scope"] == "capture"}
                if len(cities) > 1:
                    warnings.append("Embedded metadata contains different capture cities; confirm the actual photo location.")
            min_side, max_side = min(original_size), max(original_size)
            if min_side < 320:
                warnings.append("Image is very narrow or small; the legal document may be cropped or only partially visible.")
            if min_side and max_side / min_side > 3:
                warnings.append("Image aspect ratio is unusually narrow or wide; inspect for cropped or partial document content.")
            if warnings:
                metadata["warnings"] = list(dict.fromkeys(warnings))
            return metadata
    except (OSError, ValueError, TypeError, SyntaxError, IndexError, struct.error, Image.DecompressionBombError) as exc:
        raise PhotoMetadataError("Uploaded photo/screenshot is not a readable image.") from exc


def picker_capture_metadata(create_time: str, *, original_metadata: Mapping[str, Any] | None = None,
                            capture_timezone: str = "") -> dict[str, Any]:
    """Interpret trusted Picker metadata without mistaking UTC day for local day.

    Call only with createTime returned by the provider, not arbitrary user text.
    An explicit IANA timezone requires installed system/tzdata rules; if absent,
    leave the date unresolved. The host's current timezone is never substituted.
    """
    result: dict[str, Any] = {"picker_create_time": _text(create_time)}
    warnings: list[str] = []
    original = original_metadata or {}
    exif_day = _text(original.get("exif_date"))
    try:
        if exif_day:
            exif_day = date.fromisoformat(exif_day).isoformat()
    except ValueError:
        exif_day = ""
    if exif_day:
        result.update(picker_capture_date=exif_day, picker_date_source="original_exif_local_date")
    text = result["picker_create_time"]
    instant = None
    timestamp_match = _RFC3339.fullmatch(text)
    if timestamp_match and not text.endswith("-00:00"):
        # fromisoformat accepts invalid offset minutes by normalization; reject first.
        suffix = text[-6:] if not text.endswith("Z") else "+00:00"
        if _offset(suffix) is not None:
            try:
                instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
                utc = instant.astimezone(timezone.utc)
                result["picker_instant_utc"] = utc.replace(tzinfo=None, microsecond=0).isoformat() + (timestamp_match.group("fraction") or "") + "Z"
            except (ValueError, OverflowError):
                instant = None
    if instant is None:
        warnings.append("Google Photos supplied no usable creation timestamp; original EXIF or a confirmed capture date is needed.")
    else:
        saved_zone = _text(capture_timezone)
        if saved_zone:
            result["picker_capture_timezone"] = saved_zone
            try:
                zone = timezone.utc if saved_zone in {"UTC", "Etc/UTC"} else ZoneInfo(saved_zone)
                local_time = instant.astimezone(zone)
                local_day = local_time.date().isoformat()
                result["picker_time_in_saved_timezone"] = local_time.isoformat()
                result["picker_date_in_saved_timezone"] = local_day
                if exif_day and exif_day != local_day:
                    result["picker_date_conflict"] = {"original_exif": exif_day, "google_photos": local_day}
                    warnings.append("The original EXIF capture date differs from Google Photos in the saved capture timezone; review both dates.")
                elif not exif_day:
                    result.update(picker_capture_date=local_day, picker_date_source="google_photos_create_time_with_saved_timezone")
            except (ZoneInfoNotFoundError, ValueError, OSError, OverflowError):
                warnings.append("The saved capture timezone is invalid or its timezone rules are unavailable; no date was inferred from the UTC timestamp.")
        elif not exif_day:
            warnings.append("Google Photos supplied a UTC creation instant without the photo's capture timezone. Confirm its local capture date or import the original image with EXIF.")
    if warnings:
        result["warnings"] = warnings
    return result
