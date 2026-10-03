"""Synthetic, read-only Camera folder selection and local path-boundary checks."""
from __future__ import annotations

import json
from io import BytesIO
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from PIL.JpegImagePlugin import JpegImageFile

from honorarios_app import camera_folder
from honorarios_app.camera_folder import (
    CameraFolderError,
    MAX_CAMERA_FILE_BYTES,
    camera_folder_status,
    list_camera_files,
    read_camera_file,
    read_camera_thumbnail,
)
from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.web import create_app


def image_bytes(size=(1200, 600), color="red", image_format="JPEG", orientation=1, progressive=False):
    with Image.new("RGB", size, color) as source:
        source.paste("blue", (size[0] // 2, 0, size[0], size[1]))
        exif = Image.Exif()
        exif[274] = orientation
        exif[315] = "private-camera-owner"
        exif[36867] = "2026:10:02 12:00:00"
        output = BytesIO()
        source.save(output, format=image_format, exif=exif, icc_profile=b"private-profile", progressive=progressive)
        return output.getvalue()


def jpeg_header_with_size(width, height, progressive=False):
    """Synthetic oversized header only; never allocate its claimed pixel array."""
    content = bytearray(image_bytes(size=(16, 16), progressive=progressive))
    frame = content.index(b"\xff\xc2" if progressive else b"\xff\xc0")
    content[frame + 5:frame + 7] = height.to_bytes(2, "big")
    content[frame + 7:frame + 9] = width.to_bytes(2, "big")
    return bytes(content)


class CameraFolderTests(unittest.TestCase):
    def setUp(self):
        camera_folder._thumbnail_cache.clear()
        self.addCleanup(camera_folder._thumbnail_cache.clear)
        self.temp = tempfile.TemporaryDirectory(prefix="fictional-camera-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.camera = self.root / "fictional-device" / "Camera"
        self.camera.mkdir(parents=True)
        self.config = self.root / "config" / "source-import.local.json"
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({"camera_folder": str(self.camera)}), encoding="utf-8")

    def photo(self, name="20261002_122514.jpg", content=b"fictional-original-camera-bytes"):
        path = self.camera / name
        path.write_bytes(content)
        return path

    def item(self, name="20261002_122514.jpg"):
        return next(item for item in list_camera_files(self.config)["items"] if item["name"] == name)

    def test_missing_config_never_discovers_or_scans_a_phone(self):
        self.config.unlink()
        with patch("honorarios_app.camera_folder.os.scandir", side_effect=AssertionError("No device discovery")):
            self.assertEqual(camera_folder_status(self.config), {"configured": False, "label": ""})
            with self.assertRaisesRegex(CameraFolderError, "not configured"):
                list_camera_files(self.config)

    def test_status_reports_only_saved_label_without_reading_phone(self):
        with patch("honorarios_app.camera_folder.os.scandir", side_effect=AssertionError("No scan")):
            result = camera_folder_status(self.config)
        self.assertEqual(result, {"configured": True, "label": "Camera"})
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_listing_returns_only_supported_direct_nonempty_regular_files(self):
        self.photo()
        self.photo("20261003.JPG")
        self.photo("20261004.jpeg")
        self.photo("20261005.png")
        self.photo("20261006.HEIC")
        self.photo("20261007.pdf")
        self.photo("20261008.jpg", b"")
        nested = self.camera / "nested.jpg"
        nested.mkdir()
        (nested / "20261009.jpg").write_bytes(b"nested")
        result = list_camera_files(self.config)
        self.assertEqual([item["name"] for item in result["items"]], [
            "20261005.png", "20261004.jpeg", "20261003.JPG", "20261002_122514.jpg"])
        self.assertEqual(result["total"], 4)
        self.assertFalse(result["truncated"])
        for item in result["items"]:
            self.assertEqual(set(item), {"name", "size", "modified_ns", "fingerprint"})
            self.assertRegex(item["fingerprint"], "^[0-9a-f]{64}$")
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_filename_and_normalized_day_search_and_paging(self):
        for name in ("20261002_122514.jpg", "20261002_132514.jpg", "20261001_122514.jpg", "EXAMPLE_NOTE.png"):
            self.photo(name)
        result = list_camera_files(self.config, query="2026-10-02", limit=1)
        self.assertEqual(result["items"][0]["name"], "20261002_132514.jpg")
        self.assertEqual(result["next_offset"], 1)
        self.assertEqual(result["total"], 2)
        second = list_camera_files(self.config, query="2026-10-02", offset=1, limit=1)
        self.assertEqual(second["items"][0]["name"], "20261002_122514.jpg")
        self.assertIsNone(second["next_offset"])
        self.assertEqual(list_camera_files(self.config, query="example note")["total"], 1)
        self.assertEqual(list_camera_files(self.config, query="missing")["items"], [])

    def test_listing_scans_bounded_entries_and_labels_truncation(self):
        for index in range(4):
            self.photo(f"20261002_{index}.jpg")
        with patch("honorarios_app.camera_folder.MAX_CAMERA_SCAN_ENTRIES", 3):
            result = list_camera_files(self.config)
        self.assertEqual(result["total"], 3)
        self.assertTrue(result["truncated"])

    def test_listing_does_not_open_photo_contents_or_write_files(self):
        self.photo()
        original_open = Path.open
        def guarded_open(path, mode="r", *args, **kwargs):
            self.assertEqual(path, self.config)
            self.assertEqual(mode, "rb")
            return original_open(path, mode, *args, **kwargs)
        before = self.snapshot()
        with patch.object(Path, "open", guarded_open):
            result = list_camera_files(self.config)
        self.assertEqual(result["total"], 1)
        self.assertEqual(before, self.snapshot())

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def test_selected_read_preserves_exact_original_bytes_and_changes_no_files(self):
        original = b"\xff\xd8fictional-original\x00EXIF-and-GPS-bytes\xff\xd9"
        self.photo(content=original)
        item = self.item()
        before = self.snapshot()
        result = read_camera_file(self.config, item["name"], item["fingerprint"])
        self.assertEqual(result, (original, "image/jpeg", item["name"]))
        self.assertEqual(before, self.snapshot())

    def test_png_and_uppercase_extensions_return_expected_mime(self):
        for name, expected in (("sample.PNG", "image/png"), ("sample.JPEG", "image/jpeg")):
            self.photo(name)
            item = self.item(name)
            self.assertEqual(read_camera_file(self.config, name, item["fingerprint"])[1], expected)

    def test_names_reject_traversal_absolute_paths_and_windows_streams(self):
        for name in ("../outside.jpg", "..\\outside.jpg", "/outside.jpg", "C:\\outside.jpg",
                     "\\\\server\\share\\outside.jpg", "C:outside.jpg", "sample.jpg:stream",
                     "./sample.jpg", "sub/sample.jpg", ".", "..", "sample.jpg\x00", " sample.jpg", "sample.jpg ",
                     "sample\n.jpg", "", None, 4):
            with self.subTest(name=name), self.assertRaises(CameraFolderError):
                read_camera_file(self.config, name, "0" * 64)

    def test_unsupported_image_types_are_rejected(self):
        self.photo("sample.heic")
        with self.assertRaisesRegex(CameraFolderError, "JPG, JPEG or PNG"):
            read_camera_file(self.config, "sample.heic", "0" * 64)

    def test_nonregular_file_and_symlink_are_rejected_before_read(self):
        self.photo()
        original_stat = Path.stat
        for mode in (stat.S_IFDIR, stat.S_IFLNK, stat.S_IFIFO):
            def changed_stat(path, *args, **kwargs):
                info = original_stat(path, *args, **kwargs)
                if path.parent == self.camera:
                    values = list(info)
                    values[0] = mode
                    return os.stat_result(values)
                return info
            with self.subTest(mode=mode), patch.object(Path, "stat", changed_stat):
                self.assertEqual(list_camera_files(self.config)["items"], [])
                with self.assertRaisesRegex(CameraFolderError, "regular Camera photo"):
                    read_camera_file(self.config, "20261002_122514.jpg", "0" * 64)

    def test_resolved_escape_is_rejected_before_read(self):
        target = self.photo()
        original_resolve = Path.resolve
        def escaped(path, *args, **kwargs):
            return self.root / "outside.jpg" if path == target else original_resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", escaped):
            self.assertEqual(list_camera_files(self.config)["items"], [])
            with self.assertRaisesRegex(CameraFolderError, "inside the configured"):
                read_camera_file(self.config, target.name, "0" * 64)

    def test_empty_and_oversized_files_are_not_read_or_listed(self):
        self.photo("empty.jpg", b"")
        too_large = self.camera / "large.jpg"
        with too_large.open("wb") as handle:
            handle.truncate(MAX_CAMERA_FILE_BYTES + 1)
        self.assertEqual(list_camera_files(self.config)["items"], [])
        for name in ("empty.jpg", "large.jpg"):
            with self.subTest(name=name), self.assertRaisesRegex(CameraFolderError, "25 MiB"):
                read_camera_file(self.config, name, "0" * 64)

    def test_changed_size_or_mtime_rejects_old_listing(self):
        target = self.photo()
        item = self.item()
        target.write_bytes(b"changed")
        with self.assertRaisesRegex(CameraFolderError, "changed since"):
            read_camera_file(self.config, item["name"], item["fingerprint"])
        item = self.item()
        info = target.stat()
        os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 10000000))
        with self.assertRaisesRegex(CameraFolderError, "changed since"):
            read_camera_file(self.config, item["name"], item["fingerprint"])

    def test_fingerprint_is_bound_to_configured_root(self):
        target = self.photo()
        item = self.item()
        other = self.root / "other-camera"
        other.mkdir()
        other_file = other / target.name
        other_file.write_bytes(target.read_bytes())
        info = target.stat()
        os.utime(other_file, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.config.write_text(json.dumps({"camera_folder": str(other)}), encoding="utf-8")
        with self.assertRaisesRegex(CameraFolderError, "changed since"):
            read_camera_file(self.config, item["name"], item["fingerprint"])

    def test_changed_between_validation_and_open_is_rejected(self):
        target = self.photo()
        item = self.item()
        original_open = os.open
        def changed_open(path, flags, *args, **kwargs):
            target.write_bytes(b"replacement with a different size")
            return original_open(path, flags, *args, **kwargs)
        with patch("honorarios_app.camera_folder.os.open", changed_open):
            with self.assertRaisesRegex(CameraFolderError, "changed since"):
                read_camera_file(self.config, item["name"], item["fingerprint"])

    def test_changed_during_read_is_rejected_and_read_is_bounded(self):
        target = self.photo()
        item = self.item()
        original_fdopen = os.fdopen
        read_sizes = []
        class ChangingReader:
            def __init__(self, handle): self.handle = handle
            def __enter__(self): return self
            def __exit__(self, *args): self.handle.close()
            def fileno(self): return self.handle.fileno()
            def read(self, size):
                read_sizes.append(size)
                content = self.handle.read(size)
                info = target.stat()
                os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 10000000))
                return content
        with patch("honorarios_app.camera_folder.os.fdopen", lambda *a, **kw: ChangingReader(original_fdopen(*a, **kw))):
            with self.assertRaisesRegex(CameraFolderError, "changed since"):
                read_camera_file(self.config, item["name"], item["fingerprint"])
        self.assertEqual(read_sizes, [MAX_CAMERA_FILE_BYTES + 1])

    def test_invalid_fingerprint_cannot_read_a_file(self):
        self.photo()
        for value in (None, 4, "", "0", "G" * 64, "0" * 65):
            with self.subTest(value=value), self.assertRaisesRegex(CameraFolderError, "listed photo"):
                read_camera_file(self.config, "20261002_122514.jpg", value)

    def test_missing_or_offline_folder_reports_safe_actionable_error(self):
        self.camera.rmdir()
        self.assertTrue(camera_folder_status(self.config)["configured"])
        with self.assertRaisesRegex(CameraFolderError, "Connect your phone") as error:
            list_camera_files(self.config)
        self.assertNotIn(str(self.root), str(error.exception))

    def test_permission_error_does_not_expose_private_paths(self):
        with patch("honorarios_app.camera_folder.os.scandir", side_effect=PermissionError(str(self.camera))):
            with self.assertRaisesRegex(CameraFolderError, "phone connection and file access") as error:
                list_camera_files(self.config)
        self.assertNotIn(str(self.root), str(error.exception))

    def test_bad_configuration_is_rejected_without_discovery(self):
        for config in ([], "path", {"camera_folder": 4}, {"camera_folder": "relative/Camera"},
                       {"camera_folder": " "}, {"camera_folder": "\x00"}):
            self.config.write_text(json.dumps(config), encoding="utf-8")
            with self.subTest(config=config), self.assertRaises(CameraFolderError):
                camera_folder_status(self.config)
        self.config.write_bytes(b"not json")
        with self.assertRaises(CameraFolderError):
            camera_folder_status(self.config)

    def test_empty_setting_is_unconfigured(self):
        for config in ({}, {"camera_folder": None}, {"camera_folder": ""}):
            self.config.write_text(json.dumps(config), encoding="utf-8")
            self.assertFalse(camera_folder_status(self.config)["configured"])

    def test_invalid_pagination_and_query_fail_before_folder_scan(self):
        for options in ({"limit": 0}, {"limit": 51}, {"limit": True}, {"offset": -1}, {"offset": 5001},
                        {"offset": "0"}, {"query": None}, {"query": "x" * 161}):
            with self.subTest(options=options), self.assertRaises(CameraFolderError):
                list_camera_files(self.config, **options)

    def test_thumbnail_is_oriented_small_metadata_free_and_original_unchanged(self):
        original = image_bytes(orientation=6)
        self.photo(content=original)
        selected = self.item()
        before = self.snapshot()
        result = read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])
        with Image.open(BytesIO(result)) as preview:
            self.assertEqual(preview.format, "JPEG")
            self.assertEqual(preview.size, (240, 480))
            self.assertEqual(dict(preview.getexif()), {})
            self.assertNotIn("icc_profile", preview.info)
            self.assertNotIn("xmp", preview.info)
            red, _, blue = preview.getpixel((120, 80))
            self.assertGreater(red, blue + 100)
            red, _, blue = preview.getpixel((120, 400))
            self.assertGreater(blue, red + 100)
        self.assertNotIn(b"private-camera-owner", result)
        self.assertNotIn(b"2026:10:02", result)
        self.assertLessEqual(len(result), camera_folder.MAX_CAMERA_THUMBNAIL_BYTES)
        self.assertEqual(read_camera_file(self.config, selected["name"], selected["fingerprint"])[0], original)
        self.assertEqual(before, self.snapshot())

    def test_png_thumbnail_flattens_transparency_and_does_not_upscale(self):
        output = BytesIO()
        with Image.new("RGBA", (30, 20), (255, 0, 0, 0)) as source:
            source.save(output, format="PNG")
        self.photo("tiny.PNG", output.getvalue())
        selected = self.item("tiny.PNG")
        result = read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])
        with Image.open(BytesIO(result)) as preview:
            self.assertEqual(preview.size, (30, 20))
            self.assertEqual(preview.mode, "RGB")
            self.assertTrue(all(value >= 250 for value in preview.getpixel((10, 10))))

    def test_jpeg_uses_reduced_decode_before_loading_large_raster(self):
        self.photo(content=image_bytes(size=(3200, 1600)))
        selected = self.item()
        original_draft = JpegImageFile.draft
        sizes = []
        def draft(source, *args, **kwargs):
            before = source.size
            result = original_draft(source, *args, **kwargs)
            sizes.append((before, source.size))
            return result
        with patch.object(JpegImageFile, "draft", draft), patch.object(camera_folder, "MAX_CAMERA_THUMBNAIL_DECODE_PIXELS", 2_000_000):
            result = read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])
        self.assertEqual(sizes[0][0], (3200, 1600))
        self.assertLess(sizes[0][1][0] * sizes[0][1][1], 2_000_000)
        with Image.open(BytesIO(result)) as preview:
            self.assertEqual(preview.size, (480, 240))

    def test_200mp_jpeg_header_reaches_only_bounded_reduced_decode(self):
        content = jpeg_header_with_size(20000, 10000)
        original_limit = Image.MAX_IMAGE_PIXELS
        decoded_sizes = []
        class DecodeReached(Exception):
            pass
        def stop_before_pixels(source, *args, **kwargs):
            decoded_sizes.append(source.size)
            self.assertEqual(source.size, (2500, 1250))
            self.assertEqual(source.decoderconfig[0], 8)
            self.assertLessEqual(source.width * source.height, camera_folder.MAX_CAMERA_THUMBNAIL_DECODE_PIXELS)
            self.assertEqual(Image.MAX_IMAGE_PIXELS, original_limit)
            raise DecodeReached()
        with patch.object(JpegImageFile, "load", stop_before_pixels):
            with self.assertRaises(DecodeReached):
                camera_folder._thumbnail_jpeg(content)
        self.assertEqual(decoded_sizes, [(2500, 1250)])
        self.assertEqual(Image.MAX_IMAGE_PIXELS, original_limit)

    def test_jpeg_original_and_reduced_pixel_caps_reject_before_load(self):
        # A tall narrow image cannot use libjpeg's 1/8 reduction because its
        # short edge is already near the preview size; the decode cap still wins.
        non_interleaved = bytearray(jpeg_header_with_size(20000, 10000))
        scan = non_interleaved.index(b"\xff\xda")
        non_interleaved[scan + 4] = 1
        cases = [(jpeg_header_with_size(25000, 11000), False),
                 (jpeg_header_with_size(20000, 10000, progressive=True), False),
                 (bytes(non_interleaved), False),
                 (jpeg_header_with_size(40000, 600), True)]
        original_draft = JpegImageFile.draft
        for content, expected_draft in cases:
            with self.subTest(expected_draft=expected_draft):
                with patch.object(JpegImageFile, "load", side_effect=AssertionError("Must reject before decoding")), patch.object(JpegImageFile, "draft", autospec=True, side_effect=original_draft) as draft:
                    with self.assertRaisesRegex(CameraFolderError, "preview is unavailable"):
                        camera_folder._thumbnail_jpeg(content)
                self.assertEqual(draft.called, expected_draft)

    def test_invalid_or_excessive_images_fail_safely_without_changing_original(self):
        cases = [(b"corrupt-image", {}), (image_bytes(image_format="GIF"), {}),
                 (image_bytes(), {"MAX_CAMERA_THUMBNAIL_JPEG_SOURCE_PIXELS": 100}),
                 (image_bytes(image_format="PNG"), {"MAX_CAMERA_THUMBNAIL_DECODE_PIXELS": 100}),
                 (image_bytes(), {"MAX_CAMERA_THUMBNAIL_BYTES": 10})]
        for content, limits in cases:
            with self.subTest(limits=limits, size=len(content)):
                self.photo(content=content)
                selected = self.item()
                before = self.snapshot()
                with patch.multiple(camera_folder, **({"MAX_CAMERA_THUMBNAIL_SOURCE_PIXELS": camera_folder.MAX_CAMERA_THUMBNAIL_SOURCE_PIXELS} | limits)):
                    with self.assertRaisesRegex(CameraFolderError, "preview is unavailable") as error:
                        read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])
                self.assertNotIn(str(self.root), str(error.exception))
                self.assertEqual(before, self.snapshot())
                self.assertEqual(read_camera_file(self.config, selected["name"], selected["fingerprint"])[0], content)
        self.photo(content=image_bytes(image_format="PNG"))
        selected = self.item()
        with patch.object(Image, "MAX_IMAGE_PIXELS", 10):
            with self.assertRaisesRegex(CameraFolderError, "preview is unavailable"):
                read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])

    def test_cache_hit_revalidates_without_rereading_or_decoding_original(self):
        self.photo(content=image_bytes())
        selected = self.item()
        with patch.object(camera_folder, "read_camera_file", wraps=read_camera_file) as reader, patch.object(camera_folder, "_thumbnail_jpeg", wraps=camera_folder._thumbnail_jpeg) as decoder:
            first = read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])
            second = read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])
        self.assertEqual(first, second)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(decoder.call_count, 1)
        (self.camera / selected["name"]).unlink()
        with self.assertRaisesRegex(CameraFolderError, "unavailable"):
            read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])

    def test_cached_thumbnail_cannot_hide_changed_source_or_configured_root(self):
        target = self.photo(content=image_bytes())
        selected = self.item()
        read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])
        info = target.stat()
        os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 10000000))
        with self.assertRaisesRegex(CameraFolderError, "changed since"):
            read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])
        os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.config.write_text(json.dumps({"camera_folder": str(self.root / "offline")}), encoding="utf-8")
        with self.assertRaisesRegex(CameraFolderError, "Connect your phone"):
            read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])

    def test_same_size_mtime_replacement_never_reuses_cached_pixels(self):
        original, replacement = image_bytes(color="red"), image_bytes(color="green")
        length = max(len(original), len(replacement))
        target = self.photo(content=original.ljust(length, b"\x00"))
        selected = self.item()
        info = target.stat()
        first = read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])
        substitute = self.root / "replacement.jpg"
        substitute.write_bytes(replacement.ljust(length, b"\x00"))
        os.utime(substitute, ns=(info.st_atime_ns, info.st_mtime_ns))
        os.replace(substitute, target)
        self.assertEqual(self.item()["fingerprint"], selected["fingerprint"])
        with patch.object(camera_folder, "read_camera_file", wraps=read_camera_file) as reader:
            second = read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])
        self.assertNotEqual(first, second)
        self.assertEqual(reader.call_count, 1)

    def test_source_changed_while_decoding_is_not_served_or_cached(self):
        target = self.photo(content=image_bytes())
        selected = self.item()
        decoder = camera_folder._thumbnail_jpeg
        def changed(content):
            result = decoder(content)
            info = target.stat()
            os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 10000000))
            return result
        with patch.object(camera_folder, "_thumbnail_jpeg", changed):
            with self.assertRaisesRegex(CameraFolderError, "changed since"):
                read_camera_thumbnail(self.config, selected["name"], selected["fingerprint"])
        self.assertEqual(len(camera_folder._thumbnail_cache), 0)

    def test_cache_obeys_entry_and_byte_limits(self):
        for index in range(3):
            self.photo(f"photo{index}.jpg", image_bytes())
        with patch.object(camera_folder, "MAX_CAMERA_THUMBNAIL_CACHE_ENTRIES", 2):
            for item in list_camera_files(self.config)["items"]:
                read_camera_thumbnail(self.config, item["name"], item["fingerprint"])
        self.assertEqual(len(camera_folder._thumbnail_cache), 2)
        camera_folder._thumbnail_cache.clear()
        with patch.object(camera_folder, "MAX_CAMERA_THUMBNAIL_CACHE_BYTES", 9), patch.object(camera_folder, "_thumbnail_jpeg", return_value=b"12345"):
            for item in list_camera_files(self.config)["items"]:
                read_camera_thumbnail(self.config, item["name"], item["fingerprint"])
        self.assertEqual(len(camera_folder._thumbnail_cache), 1)
        self.assertLessEqual(sum(map(len, camera_folder._thumbnail_cache.values())), 9)

    def test_thumbnail_rejects_path_escape_bad_fingerprint_and_links_before_decode(self):
        target = self.photo(content=image_bytes())
        selected = self.item()
        with patch.object(camera_folder, "_thumbnail_jpeg", side_effect=AssertionError("Invalid selections must not decode")):
            for name, fingerprint in (("../outside.jpg", selected["fingerprint"]), (target.name, "bad"), (target.name, "0" * 64)):
                with self.subTest(name=name), self.assertRaises(CameraFolderError):
                    read_camera_thumbnail(self.config, name, fingerprint)
            original_resolve = Path.resolve
            def escaped(path, *args, **kwargs):
                return self.root / "outside.jpg" if path == target else original_resolve(path, *args, **kwargs)
            with patch.object(Path, "resolve", escaped):
                with self.assertRaisesRegex(CameraFolderError, "inside the configured"):
                    read_camera_thumbnail(self.config, target.name, selected["fingerprint"])


class CameraFolderRouteTests(unittest.TestCase):
    def setUp(self):
        camera_folder._thumbnail_cache.clear()
        self.addCleanup(camera_folder._thumbnail_cache.clear)
        self.temp = tempfile.TemporaryDirectory(prefix="fictional-camera-api-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        create_synthetic_runtime(self.root)
        self.camera = self.root / "fictional-phone" / "Camera"
        self.camera.mkdir(parents=True)
        self.config = self.root / "config" / "source-import.local.json"
        self.config.write_text(json.dumps({"camera_folder": str(self.camera)}), encoding="utf-8")
        self.content = b"\xff\xd8synthetic-original-camera-metadata\x00\xff\xd9"
        self.name = "20261002_120000.jpg"
        (self.camera / self.name).write_bytes(self.content)
        self.client = TestClient(create_app(**runtime_path_overrides(self.root)), base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)
        for target in ("httpx.HTTPTransport.handle_request", "honorarios_app.ai_recovery.OpenAI"):
            guard = patch(target, side_effect=AssertionError("Camera tests stay local and provider-free."))
            guard.start()
            self.addCleanup(guard.stop)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def selection(self):
        response = self.client.get("/api/camera/files")
        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        return {"name": item["name"], "fingerprint": item["fingerprint"]}

    def test_configured_routes_preserve_original_and_all_runtime_files_without_provider_calls(self):
        before = self.snapshot()
        with patch("honorarios_app.web.recover_source_upload", side_effect=AssertionError("Selection must not review/upload.")):
            status = self.client.get("/api/camera/status")
            self.assertEqual(status.json(), {"configured": True, "label": "Camera"})
            self.assertEqual(status.headers["cache-control"], "no-store")
            selected = self.selection()
            response = self.client.post("/api/camera/file", json=selected, headers={"Origin": "http://127.0.0.1:8765"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.content)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(before, self.snapshot())

    def test_unconfigured_runtime_cannot_discover_another_camera(self):
        self.config.unlink()
        with patch("honorarios_app.camera_folder.os.scandir", side_effect=AssertionError("No discovery")):
            response = self.client.get("/api/camera/status")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"configured": False, "label": ""})
            self.assertEqual(self.client.get("/api/camera/files").status_code, 400)

    def test_foreign_origin_blocks_before_selected_bytes_are_read(self):
        selected = self.selection()
        before = self.snapshot()
        with patch("honorarios_app.web.read_camera_file", side_effect=AssertionError("Origin must be checked first.")) as reader:
            response = self.client.post("/api/camera/file", json=selected, headers={"Origin": "https://foreign.invalid"})
            missing_origin = self.client.post("/api/camera/file", json=selected, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(missing_origin.status_code, 403)
        reader.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_traversal_and_stale_selections_fail_without_file_or_record_writes(self):
        selected = self.selection()
        for name in ("../outside.jpg", "sub\\outside.jpg", "C:\\outside.jpg", "/outside.jpg"):
            before = self.snapshot()
            response = self.client.post("/api/camera/file", json={**selected, "name": name})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(before, self.snapshot())
        (self.camera / self.name).write_bytes(b"changed synthetic original")
        before = self.snapshot()
        response = self.client.post("/api/camera/file", json=selected)
        self.assertEqual(response.status_code, 400)
        self.assertIn("changed since", response.json()["detail"])
        self.assertEqual(before, self.snapshot())

    def test_list_route_search_pagination_and_safe_offline_message(self):
        (self.camera / "20261003_120000.PNG").write_bytes(b"synthetic-png")
        response = self.client.get("/api/camera/files", params={"query": "2026-10-02", "limit": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["name"], self.name)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn(str(self.root), response.text)
        self.config.write_text(json.dumps({"camera_folder": str(self.root / "offline")}), encoding="utf-8")
        response = self.client.get("/api/camera/files")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Connect your phone", response.json()["detail"])
        self.assertNotIn(str(self.root), response.text)

    def test_unexpected_os_errors_are_redacted_at_every_camera_route(self):
        cases = (("camera_folder_status", "get", "/api/camera/status", {}),
                 ("list_camera_files", "get", "/api/camera/files", {}),
                 ("read_camera_file", "post", "/api/camera/file", {"json": {"name": self.name, "fingerprint": "0" * 64}}),
                 ("read_camera_thumbnail", "get", "/api/camera/thumbnail", {"params": {"name": self.name, "fingerprint": "0" * 64}}))
        secret_path = str(self.camera / "private-original.jpg")
        for function, method, route, kwargs in cases:
            with self.subTest(route=route), patch("honorarios_app.web." + function, side_effect=OSError(secret_path)):
                response = getattr(self.client, method)(route, **kwargs)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn(secret_path, response.json()["detail"])
                self.assertNotIn(str(self.root), response.json()["detail"])

    def test_thumbnail_route_is_private_local_read_only_and_original_selection_is_exact(self):
        self.content = image_bytes(orientation=6)
        (self.camera / self.name).write_bytes(self.content)
        selected = self.selection()
        before = self.snapshot()
        with patch("honorarios_app.web.recover_source_upload", side_effect=AssertionError("Preview must not review/upload.")):
            response = self.client.get("/api/camera/thumbnail", params=selected, headers={"Origin": "http://127.0.0.1:8765"})
            original = self.client.post("/api/camera/file", json=selected)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["cross-origin-resource-policy"], "same-origin")
        with Image.open(BytesIO(response.content)) as image:
            self.assertEqual(image.size, (240, 480))
            self.assertEqual(dict(image.getexif()), {})
        self.assertEqual(original.content, self.content)
        self.assertEqual(before, self.snapshot())

    def test_thumbnail_foreign_origin_and_cross_site_are_blocked_before_read(self):
        selected = self.selection()
        with patch("honorarios_app.web.read_camera_thumbnail", side_effect=AssertionError("Check origin first")) as reader:
            for headers in ({"Origin": "https://foreign.invalid"}, {"Sec-Fetch-Site": "cross-site"},
                            {"Origin": "http://127.0.0.1:9999"}, {"Origin": "null"}):
                with self.subTest(headers=headers):
                    response = self.client.get("/api/camera/thumbnail", params=selected, headers=headers)
                    self.assertEqual(response.status_code, 403)
        reader.assert_not_called()

    def test_thumbnail_errors_are_safe_and_do_not_block_selecting_original(self):
        selected = self.selection()
        before = self.snapshot()
        response = self.client.get("/api/camera/thumbnail", params=selected)
        self.assertEqual(response.status_code, 400)
        self.assertIn("preview is unavailable", response.json()["detail"])
        self.assertNotIn(str(self.root), response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.client.post("/api/camera/file", json=selected).content, self.content)
        for values in ({**selected, "name": "../private.jpg"}, {**selected, "fingerprint": "bad"}):
            response = self.client.get("/api/camera/thumbnail", params=values)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(str(self.root), response.text)
        (self.camera / self.name).write_bytes(b"changed synthetic file")
        response = self.client.get("/api/camera/thumbnail", params=selected)
        self.assertEqual(response.status_code, 400)
        self.assertIn("changed since", response.json()["detail"])
        (self.camera / self.name).write_bytes(self.content)
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
