from __future__ import annotations

from copy import deepcopy
import base64
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError

from PIL import Image
from PIL.JpegImagePlugin import JpegImageFile
from PIL.TiffImagePlugin import IFDRational

from honorarios_app.photo_metadata import (
    PhotoMetadataError,
    extract_gps_coordinates,
    extract_photo_metadata,
    picker_capture_metadata,
)
from honorarios_app.runtime import SYNTHETIC_COURT_EMAIL
from honorarios_app.gps_city import EARTH_RADIUS_M, match_verified_gps_city


CAPTURE_COURT_EMAIL = SYNTHETIC_COURT_EMAIL.replace('court@', 'fictional-capture@')


def photo_bytes(*, exif_values=None, xmp=None, size=(640, 900), progressive=False):
    image = Image.new("RGB", size, "white")
    exif = image.getexif()
    for tag, value in (exif_values or {}).items():
        exif[tag] = value
    target = BytesIO()
    options = {"exif": exif, "progressive": progressive}
    if xmp is not None:
        options["xmp"] = xmp
    image.save(target, format="JPEG", **options)
    return target.getvalue()


def gps_fields(*, lat_ref="N", lon_ref="W"):
    return {1: lat_ref, 2: (IFDRational(38), IFDRational(0), IFDRational(30)),
            3: lon_ref, 4: (IFDRational(7), IFDRational(30), IFDRational(15))}


def verified_area(**overrides):
    return {'city': 'Capture City', 'latitude': 38 + 30 / 3600,
            'longitude': -(7 + 30 / 60 + 15 / 3600), 'radius_m': 300,
            'source_url': 'https://places.example.test/fictional-area', **overrides}


class VerifiedGpsCityTests(unittest.TestCase):
    def match(self, areas, gps=None):
        area = verified_area()
        gps = gps if gps is not None else {'latitude': area['latitude'], 'longitude': area['longitude'], 'source': 'exif_gps'}
        return match_verified_gps_city({'gps_coordinates': gps}, {'verified_gps_areas': areas})

    def test_opt_in_disabled_without_catalog_and_never_mutates_original_metadata(self):
        area = verified_area()
        metadata = {'gps_coordinates': {key: area[key] for key in ('latitude', 'longitude')} | {'source': 'exif_gps'},
                    'photo_metadata_city': 'Embedded City'}
        before = deepcopy(metadata)
        self.assertEqual(match_verified_gps_city(metadata, {}), {'status': 'disabled'})
        result = match_verified_gps_city(metadata, {'verified_gps_areas': [area]})
        self.assertEqual(result['city'], 'Capture City')
        self.assertEqual(result['matches'][0]['distance_m'], 0)
        self.assertEqual(metadata, before)

    def test_circle_boundary_uses_distance_without_nearest_city_fallback(self):
        area = verified_area(latitude=0, longitude=0, radius_m=300)
        for distance, expected in ((299.99, 'matched'), (300.01, 'outside_verified_areas'), (2000, 'outside_verified_areas')):
            with self.subTest(distance=distance):
                gps = {'latitude': math.degrees(distance / EARTH_RADIUS_M), 'longitude': 0, 'source': 'exif_gps'}
                self.assertEqual(self.match([area], gps)['status'], expected)

    def test_overlap_same_normalized_city_is_one_choice_but_two_cities_are_ambiguous(self):
        matched = self.match([verified_area(), verified_area(city=' CAPTURE   CITY ')])
        self.assertEqual(matched['status'], 'matched')
        self.assertEqual(len(matched['matches']), 2)
        ambiguous = self.match([verified_area(), verified_area(city='Other City')])
        self.assertEqual(ambiguous['status'], 'ambiguous')
        self.assertNotIn('city', ambiguous)

    def test_bad_catalog_is_rejected_as_a_whole_even_without_gps(self):
        invalid = [None, {}, 'areas', [verified_area()] * 101]
        for key, values in {'city': ['', 12, '123', 'City\n'], 'radius_m': [0, -1, 500.01, True, '300', math.nan, math.inf],
                            'latitude': [True, '0', None, 91, math.nan, 10 ** 1000], 'longitude': [-181, math.inf],
                            'source_url': ['', 'http://places.example.test/', 'https://user:password@places.example.test/',
                                           'https:///missing-host', 'https://places.example.test/\x00']}.items():
            invalid.extend([verified_area(), verified_area(**{key: value})] for value in values)
        for catalog in invalid:
            with self.subTest(catalog=str(catalog)[:150]):
                self.assertEqual(match_verified_gps_city({}, {'verified_gps_areas': catalog})['status'], 'invalid_configuration')

    def test_invalid_or_missing_original_gps_never_becomes_zero(self):
        self.assertEqual(match_verified_gps_city({}, {'verified_gps_areas': [verified_area()]})['status'], 'missing_gps')
        for gps in ({}, [], {'latitude': 0, 'longitude': 0},
                    *({'latitude': bad, 'longitude': 0, 'source': 'exif_gps'} for bad in (None, True, '0', math.nan, math.inf, 91, 10 ** 1000))):
            with self.subTest(gps=str(gps)[:150]):
                self.assertEqual(self.match([verified_area(latitude=0, longitude=0)], gps)['status'], 'invalid_gps')
        self.assertEqual(self.match([verified_area(latitude=0, longitude=0)],
            {'latitude': 0, 'longitude': 0, 'source': 'exif_gps'})['status'], 'matched')


class ConfirmedVenueTravelTests(unittest.TestCase):
    def test_prosecutor_inquiry_section_before_city_uses_only_unambiguous_saved_distance(self):
        from honorarios_app.personal_profiles import lookup_profile_distance
        host = 'Procuradoria do Juízo Local Criminal - 1ª Sec Inquéritos de Capture City'
        profile = {'travel_distances_by_city': {'Capture City': 31, 'Other City': 29, 'GNR de Capture City': 43}}
        for venue, expected in (
            (host, (31, 'Capture City')),
            ('Ministério Público de Capture City', (31, 'Capture City')),
            ('Procuradoria de Capture City', (31, 'Capture City')),
            ('Procuradoria de Unknown City - Unidade de Capture City', (None, '')),
            ('Procuradoria de Other City - 1ª Sec Inquéritos de Capture City', (None, '')),
            ('Procuradoria do Juízo Local Criminal - Unidade de Capture City', (None, '')),
            (host + ' - Unidade de Other City', (None, '')),
        ):
            with self.subTest(venue=venue):
                self.assertEqual(lookup_profile_distance(profile, venue), expected)
        profile['travel_distances_by_city'][host] = 35
        self.assertEqual(lookup_profile_distance(profile, host), (35, host))

    def test_known_venue_city_before_unit_keeps_specific_station_priority_and_rejects_ambiguous_cities(self):
        from honorarios_app.personal_profiles import lookup_profile_distance
        profile = {'travel_distances_by_city': {'Capture City': 31, 'Other City': 29, 'GNR de Capture City': 43}}
        for venue, expected in (
            ('GNR de Capture City — Unidade de Apoio', (43, 'GNR de Capture City')),
            ('Tribunal de Capture City — Sala de audiência', (31, 'Capture City')),
            ('GNR de Capture City (Unidade de Apoio)', (43, 'GNR de Capture City')),
            ('GNR de Capture City — Unidade de Other City', (None, '')),
            ('GNR de Unknown City — Unidade de Capture City', (None, '')),
            ('Comando territorial de Capture City', (None, '')),
            ('Polícia Judiciária', (None, '')),
        ):
            with self.subTest(venue=venue):
                self.assertEqual(lookup_profile_distance(profile, venue), expected)

    def test_manual_distance_or_destination_remains_authoritative(self):
        from honorarios_app.personal_profiles import apply_profile_defaults_to_intake
        profile = {'travel_distances_by_city': {'Capture City': 31, 'Other City': 29}}
        base = {'service_place': 'GNR de Capture City — Unidade de Apoio', 'claim_transport': True}
        for given, expected in (({'km_one_way': 37}, {'destination': 'Capture City', 'km_one_way': 37}),
                                 ({'km_one_way': 0}, {'destination': 'Capture City', 'km_one_way': 0}),
                                 ({'destination': 'Other City'}, {'destination': 'Other City', 'km_one_way': 29}),
                                 ({'destination': 'Manual destination', 'km_one_way': 37}, {'destination': 'Manual destination', 'km_one_way': 37})):
            with self.subTest(given=given):
                intake = {**base, 'transport': given}
                before = deepcopy(intake)
                effective, _ = apply_profile_defaults_to_intake(intake, profile)
                self.assertEqual(effective['transport'], expected)
                self.assertEqual(intake, before)

    def test_recovered_mp_venue_preserves_manual_distance_zero_and_destination(self):
        from honorarios_app.personal_profiles import apply_profile_defaults_to_intake
        host = 'Procuradoria do Juízo Local Criminal - 2ª Sec Inquéritos de Capture City'
        profile = {'travel_distances_by_city': {'Capture City': 31, 'Other City': 29}}
        for transport in ({'destination': host, 'km_one_way': 0},
                          {'destination': host, 'km_one_way': 37},
                          {'destination': 'Manual City', 'km_one_way': 15}):
            with self.subTest(transport=transport):
                intake = {'service_place': host, 'claim_transport': True, 'transport': transport}
                effective, _ = apply_profile_defaults_to_intake(intake, profile)
                self.assertEqual(effective['transport'], transport)


class PhotoMetadataTests(unittest.TestCase):
    def test_large_original_jpeg_metadata_validates_reduced_pixels_and_keeps_original_facts(self):
        original = photo_bytes(size=(3200, 1600), exif_values={
            274: 6, 34665: {36867: "2026:07:02 00:15:00", 36881: "+01:00"},
            34853: gps_fields(),
        }, xmp=location_xmp(capture_cities=("Capture City",)))
        digest = hashlib.sha256(original).hexdigest()
        native_load = JpegImageFile.load
        decoded = []
        def bounded_load(image, *args, **kwargs):
            decoded.append(image.size)
            self.assertLessEqual(image.width * image.height, 2_000_000)
            return native_load(image, *args, **kwargs)
        global_limit = Image.MAX_IMAGE_PIXELS
        with patch('honorarios_app.photo_metadata.MAX_CAMERA_THUMBNAIL_DECODE_PIXELS', 2_000_000), \
                patch.object(JpegImageFile, 'load', bounded_load):
            metadata = extract_photo_metadata(original)
        self.assertTrue(decoded)
        self.assertEqual((metadata['width'], metadata['height']), (3200, 1600))
        self.assertEqual(metadata['exif_date'], '2026-07-02')
        self.assertEqual(metadata['exif_orientation'], 6)
        self.assertEqual(metadata['exif_capture_instant'], '2026-07-01T23:15:00Z')
        self.assertAlmostEqual(metadata['gps_coordinates']['latitude'], 38.0083333333)
        self.assertAlmostEqual(metadata['gps_coordinates']['longitude'], -7.5041666667)
        self.assertEqual(metadata['embedded_location_candidates'][0]['city'], 'Capture City')
        self.assertFalse(any('very narrow or small' in warning for warning in metadata.get('warnings', [])))
        self.assertEqual(hashlib.sha256(original).hexdigest(), digest)
        self.assertEqual(Image.MAX_IMAGE_PIXELS, global_limit)

    def test_200mp_original_header_reaches_only_bounded_validation_and_keeps_original_dimensions(self):
        # Deliberately header-only: stop at the decoder boundary rather than
        # allocating a 200 MP synthetic raster. Actual decode is tested above.
        original = bytearray(photo_bytes(size=(16, 16), exif_values={
            34665: {36867: '2026:07:02 00:15:00', 36881: '+01:00'}, 34853: gps_fields(),
        }))
        frame = original.index(b'\xff\xc0')
        original[frame + 5:frame + 7] = (10000).to_bytes(2, 'big')
        original[frame + 7:frame + 9] = (20000).to_bytes(2, 'big')
        sizes = []
        global_limit = Image.MAX_IMAGE_PIXELS
        def stop_at_decoder(image):
            sizes.append(image.size)
            self.assertEqual(image.size, (2500, 1250))
            self.assertEqual(image.decoderconfig[0], 8)
            self.assertEqual(Image.MAX_IMAGE_PIXELS, global_limit)
        with patch.object(JpegImageFile, 'load', stop_at_decoder):
            metadata = extract_photo_metadata(bytes(original))
        self.assertEqual(sizes, [(2500, 1250)])
        self.assertEqual((metadata['width'], metadata['height']), (20000, 10000))
        self.assertEqual(metadata['exif_date'], '2026-07-02')
        self.assertIn('gps_coordinates', metadata)
        self.assertEqual(Image.MAX_IMAGE_PIXELS, global_limit)

    def test_excessive_progressive_and_noninterleaved_jpeg_reject_before_decoding(self):
        for size, progressive, noninterleaved in (
                ((25000, 11000), False, False), ((20000, 10000), True, False),
                ((20000, 10000), False, True), ((40000, 600), False, False)):
            with self.subTest(size=size, progressive=progressive, noninterleaved=noninterleaved):
                content = bytearray(photo_bytes(size=(16, 16), progressive=progressive))
                frame = content.index(b'\xff\xc2' if progressive else b'\xff\xc0')
                content[frame + 5:frame + 7] = size[1].to_bytes(2, 'big')
                content[frame + 7:frame + 9] = size[0].to_bytes(2, 'big')
                if noninterleaved:
                    scan = content.index(b'\xff\xda')
                    content[scan + 4] = 1
                with patch.object(JpegImageFile, 'load', side_effect=AssertionError('Must not decode')):
                    with self.assertRaises(PhotoMetadataError):
                        extract_photo_metadata(bytes(content))

    def test_reduced_jpeg_validation_rejects_truncated_pixels_and_keeps_small_progressive_support(self):
        content = photo_bytes(size=(3200, 1600))
        with self.assertRaises(PhotoMetadataError):
            extract_photo_metadata(content[:len(content) // 2])
        small = extract_photo_metadata(photo_bytes(size=(640, 900), progressive=True))
        self.assertEqual((small['width'], small['height']), (640, 900))

    def test_ocr_payload_preserves_original_image_bytes_after_metadata_validation(self):
        from honorarios_app.ai_recovery import _content_item_for_source
        original = photo_bytes(size=(3200, 1600), exif_values={34853: gps_fields()})
        extract_photo_metadata(original)
        payload = _content_item_for_source(original, 'photo', 'fictional-original.jpg', 'image/jpeg')
        self.assertEqual(base64.b64decode(payload['image_url'].split(',', 1)[1]), original)
        self.assertEqual(payload['detail'], 'high')

    def test_real_jpeg_nested_original_offset_preserves_local_day(self):
        result = extract_photo_metadata(photo_bytes(exif_values={
            34665: {36867: "2026:07:02 00:15:00", 36881: "+01:00", 36868: "2026:07:03 13:00:00"},
            306: "2026:10:02 15:00:00", 34853: gps_fields(),
        }))
        self.assertEqual(result["exif_date"], "2026-07-02")
        self.assertEqual(result["exif_date_source"], "DateTimeOriginal")
        self.assertEqual(result["exif_capture_time"], "2026-07-02T00:15:00")
        self.assertEqual(result["exif_utc_offset"], "+01:00")
        self.assertEqual(result["exif_capture_instant"], "2026-07-01T23:15:00Z")
        self.assertAlmostEqual(result["gps_coordinates"]["latitude"], 38.0083333333)
        self.assertAlmostEqual(result["gps_coordinates"]["longitude"], -7.5041666667)
        self.assertNotIn("capture_city", result)
        json.dumps(result, allow_nan=False)

    def test_top_level_original_still_beats_nested_digitized_date(self):
        result = extract_photo_metadata(photo_bytes(exif_values={
            36867: "2026:09:26 09:15:00", 34665: {36868: "2026:09:28 09:15:00"},
        }))
        self.assertEqual(result["exif_date"], "2026-09-26")
        self.assertEqual(result["exif_date_source"], "DateTimeOriginal")

    def test_digitized_fallback_has_distinct_provenance_and_matching_offset(self):
        result = extract_photo_metadata(photo_bytes(exif_values={
            34665: {36868: "2026:09:26 23:15:00", 36881: "+02:00", 36882: "-02:00"},
        }))
        self.assertEqual(result["exif_date_source"], "DateTimeDigitized")
        self.assertEqual(result["exif_capture_instant"], "2026-09-27T01:15:00Z")

    def test_modification_and_gps_clock_cannot_supply_capture_day(self):
        result = extract_photo_metadata(photo_bytes(exif_values={306: "2026:10:02 12:00:00",
            34853: {**gps_fields(), 29: "2026:10:02"}}))
        self.assertNotIn("exif_date", result)
        self.assertTrue(any("modification date" in warning for warning in result["warnings"]))

    def test_invalid_original_date_is_not_truncated_into_valid_date(self):
        for value in ("2026:02:30 12:00:00", "2026:09:01 12:00:00 extra", "2026:09:01 25:00:00"):
            with self.subTest(value=value):
                result = extract_photo_metadata(photo_bytes(exif_values={36867: value}))
                self.assertNotIn("exif_date", result)
                self.assertTrue(any("invalid" in warning for warning in result["warnings"]))

    def test_unknown_or_invalid_offset_keeps_date_but_does_not_invent_instant(self):
        for offset in ("-00:00", "+24:00", "+01:75", "Europe/Lisbon"):
            with self.subTest(offset=offset):
                result = extract_photo_metadata(photo_bytes(exif_values={
                    34665: {36867: "2026:07:02 00:15:00", 36881: offset}}))
                self.assertEqual(result["exif_date"], "2026-07-02")
                self.assertNotIn("exif_capture_instant", result)

    def test_original_without_offset_has_no_implicit_host_timezone(self):
        result = extract_photo_metadata(photo_bytes(exif_values={36867: "2026:07:02 00:15:00"}))
        self.assertEqual(result["exif_capture_time"], "2026-07-02T00:15:00")
        self.assertNotIn("exif_capture_instant", result)

    def test_out_of_range_exif_instant_keeps_readable_image_and_local_date(self):
        result = extract_photo_metadata(photo_bytes(exif_values={
            34665: {36867: "0001:01:01 00:00:00", 36881: "+01:00"}}))
        self.assertEqual(result["exif_date"], "0001-01-01")
        self.assertNotIn("exif_capture_instant", result)
        self.assertTrue(any("supported date range" in value for value in result["warnings"]))

    def test_real_jpeg_bad_gps_stays_location_evidence_warning(self):
        gps = gps_fields()
        gps[1] = "?"
        result = extract_photo_metadata(photo_bytes(exif_values={34853: gps}))
        self.assertNotIn("gps_coordinates", result)
        self.assertTrue(any("GPS" in warning for warning in result["warnings"]))

    def test_orientation_and_image_shape_warnings_are_preserved(self):
        result = extract_photo_metadata(photo_bytes(exif_values={274: 6}, size=(100, 900)))
        self.assertEqual(result["exif_orientation"], 6)
        self.assertEqual(len(result["warnings"]), 3)

    def test_invalid_image_is_reported_explicitly(self):
        with self.assertRaises(PhotoMetadataError):
            extract_photo_metadata(b"not an image")

    def test_gps_hemispheres_and_rational_pairs(self):
        gps = {1: b"S\0", 2: ((38, 1), (1, 2), (30, 1)),
               3: b"E\0", 4: ((7, 1), (30, 1), (0, 1))}
        before = deepcopy(gps)
        result = extract_gps_coordinates(gps)
        self.assertAlmostEqual(result["latitude"], -(38 + 0.5 / 60 + 30 / 3600))
        self.assertEqual(result["longitude"], 7.5)
        self.assertEqual(before, gps)

    def test_gps_rejects_missing_hemisphere_bounds_nonfinite_and_bad_rationals(self):
        invalid = [
            {1: ""}, {3: "North"}, {2: (91, 0, 0)}, {2: (90, 0, 1)},
            {4: (180, 0, 1)}, {4: (-7, 0, 0)}, {2: (38, 60, 0)},
            {2: (38, 0, 60)}, {2: (38, 0)}, {2: (float("nan"), 0, 0)},
            {2: (38, float("inf"), 0)}, {2: ((1, 0), 0, 0)},
            {2: (True, 0, 0)}, {2: ("38", 0, 0)}, {2: (IFDRational(0, 0), 0, 0)},
        ]
        for replacement in invalid:
            with self.subTest(replacement=replacement):
                self.assertIsNone(extract_gps_coordinates({**gps_fields(), **replacement}))

    def test_gps_boundaries_and_zero_remain_coordinates_not_inferred_city(self):
        for latitude, longitude in ((90, 180), (0, 0)):
            result = extract_gps_coordinates({1: "N", 2: (latitude, 0, 0), 3: "W", 4: (longitude, 0, 0)})
            self.assertEqual(result["latitude"], latitude)
            self.assertEqual(result["longitude"], -longitude)
            self.assertNotIn("city", result)

    def test_xmp_location_created_is_distinct_from_shown_and_legacy_city(self):
        xmp = b'''<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
            xmlns:ext="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" xmlns:ps="http://ns.adobe.com/photoshop/1.0/">
            <rdf:RDF><rdf:Description ps:City="Legacy City"><ext:LocationCreated><rdf:Bag><rdf:li>
            <ext:City>Capture City</ext:City></rdf:li></rdf:Bag></ext:LocationCreated>
            <ext:LocationShown><rdf:Bag><rdf:li ext:City="Shown City"/></rdf:Bag></ext:LocationShown>
            </rdf:Description></rdf:RDF></x:xmpmeta>'''
        result = extract_photo_metadata(photo_bytes(xmp=xmp))
        rows = result["embedded_location_candidates"]
        self.assertIn({"city": "Capture City", "source": "xmp_LocationCreated", "scope": "capture"}, rows)
        self.assertIn({"city": "Shown City", "source": "xmp_LocationShown", "scope": "shown"}, rows)
        self.assertIn({"city": "Legacy City", "source": "xmp_photoshop_city", "scope": "unspecified"}, rows)
        self.assertNotIn("capture_city", result)

    def test_xmp_entity_or_malformed_xml_does_not_supply_city(self):
        for xmp in (b'<!DOCTYPE city [<!ENTITY name "City">]><city>&name;</city>', b'<invalid',
                    '<!DOCTYPE city [<!ENTITY name "City">]><city>&name;</city>'.encode("utf-16")):
            with self.subTest(xmp=xmp):
                result = extract_photo_metadata(photo_bytes(xmp=xmp))
                self.assertNotIn("embedded_location_candidates", result)
                self.assertTrue(any("XMP" in warning for warning in result["warnings"]))

    def test_iptc_legacy_city_is_never_marked_capture(self):
        with patch("honorarios_app.photo_metadata.IptcImagePlugin.getiptcinfo", return_value={(2, 90): b"Example City"}):
            result = extract_photo_metadata(photo_bytes())
        self.assertEqual(result["embedded_location_candidates"], [
            {"city": "Example City", "source": "iptc_legacy_city", "scope": "unspecified"}])


class PickerCaptureMetadataTests(unittest.TestCase):
    def test_utc_instant_alone_never_becomes_unqualified_capture_date(self):
        result = picker_capture_metadata("2026-07-01T23:30:00Z")
        self.assertEqual(result["picker_instant_utc"], "2026-07-01T23:30:00Z")
        self.assertNotIn("picker_capture_date", result)
        self.assertTrue(result["warnings"])

    def test_explicit_portugal_timezone_handles_midnight_summer_and_winter(self):
        summer = picker_capture_metadata("2026-07-01T23:30:00Z", capture_timezone="Europe/Lisbon")
        winter = picker_capture_metadata("2026-01-01T23:30:00Z", capture_timezone="Europe/Lisbon")
        self.assertEqual(summer["picker_capture_date"], "2026-07-02")
        self.assertEqual(winter["picker_capture_date"], "2026-01-01")

    def test_real_dst_rules_handle_both_transition_directions(self):
        cases = [("2026-03-29T00:30:00Z", "2026-03-29T00:30:00+00:00"),
                 ("2026-03-29T01:30:00Z", "2026-03-29T02:30:00+01:00"),
                 ("2026-10-25T00:30:00Z", "2026-10-25T01:30:00+01:00"),
                 ("2026-10-25T01:30:00Z", "2026-10-25T01:30:00+00:00")]
        for instant, expected in cases:
            with self.subTest(instant=instant):
                result = picker_capture_metadata(instant, capture_timezone="Europe/Lisbon")
                self.assertEqual(result["picker_time_in_saved_timezone"], expected)

    def test_explicit_azores_timezone_is_not_replaced_by_mainland_timezone(self):
        result = picker_capture_metadata("2026-01-02T00:30:00Z", capture_timezone="Atlantic/Azores")
        self.assertEqual(result["picker_capture_date"], "2026-01-01")

    def test_original_exif_day_wins_with_visible_google_photos_conflict(self):
        original = {"exif_date": "2026-07-01", "exif_capture_time": "2026-07-01T21:00:00"}
        before = deepcopy(original)
        result = picker_capture_metadata("2026-07-01T23:30:00Z", original_metadata=original,
                                         capture_timezone="Europe/Lisbon")
        self.assertEqual(result["picker_capture_date"], "2026-07-01")
        self.assertEqual(result["picker_date_source"], "original_exif_local_date")
        self.assertEqual(result["picker_date_conflict"], {"original_exif": "2026-07-01", "google_photos": "2026-07-02"})
        self.assertEqual(original, before)

    def test_original_exif_day_needs_no_capture_timezone(self):
        result = picker_capture_metadata("2026-07-01T23:30:00Z", original_metadata={"exif_date": "2026-07-02"})
        self.assertEqual(result["picker_capture_date"], "2026-07-02")
        self.assertNotIn("warnings", result)

    def test_offset_input_retains_nanosecond_instant_precision(self):
        result = picker_capture_metadata("2026-07-02T00:30:00.123456789+01:00", capture_timezone="Europe/Lisbon")
        self.assertEqual(result["picker_instant_utc"], "2026-07-01T23:30:00.123456789Z")
        self.assertEqual(result["picker_capture_date"], "2026-07-02")

    def test_bad_timestamps_are_not_normalized_into_valid_capture_dates(self):
        for value in ("2026-02-30T12:00:00Z", "2026-07-01", "2026-07-01T23:30:00",
                      "2026-07-01T23:30:00-00:00", "2026-07-01T23:30:00+01:75", "2026-07-01T25:30:00Z",
                      "0001-01-01T00:00:00+01:00"):
            with self.subTest(value=value):
                result = picker_capture_metadata(value, capture_timezone="UTC")
                self.assertNotIn("picker_capture_date", result)
                self.assertNotIn("picker_instant_utc", result)

    def test_missing_timezone_database_and_invalid_zone_fail_honestly(self):
        with patch("honorarios_app.photo_metadata.ZoneInfo", side_effect=ZoneInfoNotFoundError("unavailable")):
            result = picker_capture_metadata("2026-07-01T23:30:00Z", capture_timezone="Europe/Lisbon")
        self.assertNotIn("picker_capture_date", result)
        self.assertTrue(any("unavailable" in warning for warning in result["warnings"]))
        invalid = picker_capture_metadata("2026-07-01T23:30:00Z", capture_timezone="/bad/path")
        self.assertNotIn("picker_capture_date", invalid)

    def test_explicit_utc_works_without_external_timezone_rules(self):
        with patch("honorarios_app.photo_metadata.ZoneInfo", side_effect=AssertionError("should not load")):
            result = picker_capture_metadata("2026-07-01T23:30:00Z", capture_timezone="UTC")
        self.assertEqual(result["picker_capture_date"], "2026-07-01")


def location_xmp(*, capture_cities=(), shown_city="", legacy_city=""):
    # Fixtures intentionally use simple fictional names, never private locations.
    created = "".join(f'<rdf:li><ext:City>{city}</ext:City></rdf:li>' for city in capture_cities)
    return (f'<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
            f'xmlns:ext="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" xmlns:ps="http://ns.adobe.com/photoshop/1.0/">'
            f'<rdf:RDF><rdf:Description ps:City="{legacy_city}"><ext:LocationCreated><rdf:Bag>{created}'
            f'</rdf:Bag></ext:LocationCreated><ext:LocationShown><rdf:Bag><rdf:li ext:City="{shown_city}"/>'
            f'</rdf:Bag></ext:LocationShown></rdf:Description></rdf:RDF></x:xmpmeta>').encode("utf-8")


class PhotoMetadataUploadIntegrationTests(unittest.TestCase):
    """Public original-byte uploads through the real shared review and guards."""

    def setUp(self):
        from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
        from honorarios_app.services import AppPaths
        temporary = tempfile.TemporaryDirectory(prefix="fee-photo-metadata-public-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        self.preferences_path = self.paths.ai_config.with_name("photo-defaults.local.json")
        self.preferences = {
            "capture_date_is_service_date": True, "photo_city_court": True,
            "missing_venue_is_city_court": True,
            "capture_timezone": "Europe/Lisbon",
            "city_courts": {"Capture City": {
                "payment_entity": "Tribunal de Capture City", "addressee": "Tribunal de Capture City",
                "recipient_email": CAPTURE_COURT_EMAIL,
            }},
        }
        contacts = json.loads(self.paths.court_emails.read_text(encoding="utf-8"))
        contacts.append({"key": "capture-city", "name": "Tribunal de Capture City",
                         "email": CAPTURE_COURT_EMAIL,
                         "payment_entity_aliases": ["Tribunal de Capture City"]})
        self.paths.court_emails.write_text(json.dumps(contacts), encoding="utf-8")
        network = patch("socket.socket.connect", side_effect=AssertionError("Metadata acceptance must stay offline."))
        network.start()
        self.addCleanup(network.stop)

    def upload(self, *, original_day="2026:07:02 00:15:00", picker_time=None, capture_cities=("Capture City",),
               shown_city="", legacy_city="", filename="fictional-photo.jpg", source_extra="", ai_fields=None,
               source_text=None, profile_name="auto", size=(640, 900)):
        from honorarios_app.services import recover_source_upload
        self.preferences_path.write_text(json.dumps(self.preferences), encoding="utf-8")
        values = {34853: gps_fields()}
        if original_day:
            values[34665] = {36867: original_day, 36881: "+01:00"}
        content = photo_bytes(size=size, exif_values=values, xmp=location_xmp(
            capture_cities=capture_cities, shown_city=shown_city, legacy_city=legacy_city))
        source_text = source_text or ("POLICIA DE SEGURANCA PUBLICA\nEsquadra de Example City\n"
                       "Processo 710/26.0TSTXX\nServico de interpretacao presencial.\n" + source_extra)
        fields = {"case_number": "710/26.0TSTXX", "service_entity": "Esquadra de Example City",
                  "service_entity_type": "psp", "service_place": "Esquadra de Example City", "locality": "Example City",
                  **(ai_fields or {})}
        replay = {"status": "ok", "attempted": False, "provider": "fictional-offline-replay",
                  "fields": fields, "raw_visible_text": source_text, "warnings": [], "translation_indicators": []}
        managed = [*self.root.joinpath("config").glob("*.json"), *self.root.joinpath("data").glob("*.json")]
        before = {path: path.read_bytes() for path in managed}
        provider_metadata = None if picker_time is None else {"google_photos_create_time": picker_time}
        visible_text = source_text if picker_time is None else filename + "\n" + source_text
        def offline_recovery(**kwargs):
            self.assertNotIn('gps_city_match', kwargs['source_metadata'], 'Private GPS area matches stay local, outside provider input.')
            return replay
        with patch("honorarios_app.services.recover_source_with_openai", side_effect=offline_recovery) as recovery:
            result = recover_source_upload(filename=filename, content_type="image/jpeg", content=content,
                source_kind="photo", profile_name=profile_name, visible_text=visible_text, ai_recovery_mode="off",
                provider_metadata=provider_metadata, paths=self.paths)
        self.assertEqual(recovery.call_args.kwargs['content'], content)
        self.assertEqual(recovery.call_count, 1, 'Local GPS matching must not retry or add provider reads.')
        self.assertEqual(Path(result['source']['stored_path']).read_bytes(), content)
        self.assertEqual(result['source']['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual({path: path.read_bytes() for path in managed}, before)
        for directory in (self.paths.output_dir, self.paths.draft_output_dir,
                          self.paths.intake_output_dir, self.paths.manifest_dir):
            self.assertEqual(list(directory.rglob("*")), [])
        self.assertFalse(result["send_allowed"])
        self.assertFalse(result["review"]["send_allowed"])
        return result

    def test_reduced_decode_original_upload_keeps_metadata_original_bytes_and_saved_defaults(self):
        with patch('honorarios_app.photo_metadata.MAX_CAMERA_THUMBNAIL_DECODE_PIXELS', 2_000_000):
            result = self.upload(size=(3200, 1600))
        self.assertEqual((result['source']['metadata']['width'], result['source']['metadata']['height']),
                         (3200, 1600))
        self.assertIn('gps_coordinates', result['source']['metadata'])
        self.assertEqual(result['candidate_intake']['service_date'], '2026-07-02')
        self.assertEqual(result['candidate_intake']['payment_entity'], 'Tribunal de Capture City')
        self.assertEqual(result['review']['status'], 'ready')

    def test_original_jpeg_capture_date_gps_and_explicit_creation_city_need_no_screenshot(self):
        result = self.upload(filename="IMG_20260101-renamed.jpg", shown_city="Other City", legacy_city="Legacy City")
        candidate = result["candidate_intake"]
        self.assertEqual(candidate["service_date"], "2026-07-02")
        self.assertEqual(candidate["payment_entity"], "Tribunal de Capture City")
        self.assertEqual(candidate["recipient_email"], CAPTURE_COURT_EMAIL)
        self.assertEqual(candidate["service_place"], "Esquadra de Example City")
        self.assertEqual(result["review"]["status"], "ready")
        metadata = result["source"]["metadata"]
        self.assertEqual(metadata["photo_metadata_city"], "Capture City")
        self.assertNotIn("visible_metadata_date", metadata)
        evidence = {row["field"]: row for row in result["source_evidence"]["field_evidence"]}
        self.assertEqual(evidence["photo_metadata_city"]["source"], "embedded_location_created")
        self.assertEqual(evidence["photo_gps"]["source"], "exif_gps")

    def test_source_station_is_preserved_without_missing_venue_default(self):
        for setting in (False, None):
            with self.subTest(setting=setting):
                if setting is None:
                    self.preferences.pop("missing_venue_is_city_court", None)
                else:
                    self.preferences["missing_venue_is_city_court"] = setting
                result = self.upload()
                candidate = result["candidate_intake"]
                self.assertEqual(candidate["service_place"], "Esquadra de Example City")
                self.assertEqual(candidate["service_entity"], "Esquadra de Example City")
                self.assertIn("Esquadra de Example City", candidate["service_place_phrase"])
                self.assertEqual(result["review"]["status"], "ready")

    def test_district_header_cannot_supply_physical_host_or_travel_destination(self):
        from honorarios_app.services import extract_candidate_fields
        fields = extract_candidate_fields("COMANDO DISTRITAL DE Example City\nProcesso 710/26.0TSTXX",
                                           self.paths, source_kind="photo")
        self.assertNotIn("transport_destination", fields)
        self.assertNotIn("km_one_way", fields)
        self.assertNotIn("service_place", fields)

    def test_explicit_service_host_wins_over_issuer_station_header(self):
        from honorarios_app.services import extract_candidate_fields
        text = ("Esquadra de Issuer City\nProcesso 710/26.0TSTXX\n"
                "Diligência de interpretação realizada no Hospital de Example City.")
        fields = extract_candidate_fields(text, self.paths, source_kind="photo")
        self.assertEqual(fields["service_place"], "Hospital de Example City")

    def test_grounded_ai_host_fills_only_missing_venue_and_coherent_service_entity(self):
        from honorarios_app.services import merge_ai_recovery_into_intake
        host = "Esquadra de Example City"
        replay = {"status": "ok", "fields": {"service_place": host, "locality": "Example City"},
                  "raw_visible_text": host}
        promoted = merge_ai_recovery_into_intake({"service_place": "", "service_entity": "Example Court",
            "service_entity_type": "court", "entities_differ": False}, replay)
        self.assertEqual(promoted["service_place"], host)
        self.assertIn(host, promoted["service_place_phrase"])
        self.assertEqual(promoted['service_entity'], host)
        self.assertNotEqual(promoted['service_entity_type'], 'court')
        self.assertTrue(promoted['entities_differ'])
        for place, extra in (("Example City", {}), ("Example Police Station", {}), ("Posto da GNR de Manual City", {}),
                             ("Example City", {"review_cleared_fields": ["service_place"]})):
            with self.subTest(place=place, extra=extra):
                kept = merge_ai_recovery_into_intake({"service_place": place, **extra}, replay)
                self.assertEqual(kept["service_place"], place)
        unsupported = merge_ai_recovery_into_intake({"service_place": "Example City"},
            {**replay, "raw_visible_text": "Unreadable venue"})
        self.assertEqual(unsupported["service_place"], "Example City")

    def test_ai_hospital_host_preserves_pj_entity_and_manual_city(self):
        from honorarios_app.services import merge_ai_recovery_into_intake
        host = 'Hospital de Capture City'
        replay = {'status': 'ok', 'raw_visible_text': host, 'fields': {'service_place': host, 'locality': 'Capture City'}}
        for context, expected in (('', host), ('Polícia Judiciária', 'Polícia Judiciária')):
            result = merge_ai_recovery_into_intake({'service_place': '', 'source_text': context,
                'transport': {'destination': 'Example City', 'km_one_way': 12},
                'service_entity': 'Example Court', 'service_entity_type': 'court', 'entities_differ': False}, replay)
            self.assertEqual(result['service_place'], host)
            self.assertEqual(result['service_entity'], expected)
            self.assertTrue(result['entities_differ'])
            self.assertEqual(result['transport']['destination'], host)
            self.assertFalse(result['transport'].get('km_one_way'))
        manual = {'service_place': 'Capture City', 'service_entity': 'Tribunal de Capture City',
                  'service_entity_type': 'court', 'entities_differ': False, 'service_place_phrase': 'em Capture City'}
        replay['fields']['service_entity_type'] = 'other'
        kept = merge_ai_recovery_into_intake(deepcopy(manual), replay)
        for key, value in manual.items():
            self.assertEqual(kept[key], value)

    def test_actual_station_replaces_district_distance_and_profile_merge_cannot_restore_it(self):
        from honorarios_app.services import extract_candidate_fields, review_intake_with_profile_evidence, preflight_intakes
        host = 'Posto Territorial de Capture City'
        source = 'COMANDO DISTRITAL DE Example City\n' + host + '\nProcesso 710/26.0TSTXX\nServico de interpretacao presencial.'
        fields = extract_candidate_fields(source, self.paths, source_kind='photo')
        self.assertEqual(fields['service_place'], host)
        self.assertEqual(fields['transport_destination'], host)
        self.assertNotIn('km_one_way', fields)
        result = self.upload(source_text=source, profile_name='example_interpreting',
            ai_fields={'service_place': host, 'locality': 'Capture City', 'service_entity': host, 'service_entity_type': 'gnr'})
        candidate = result['candidate_intake']
        self.assertEqual(candidate['transport']['destination'], host)
        self.assertFalse(candidate['transport'].get('km_one_way'))
        candidate['auto_profile']['auto_applied'] = True
        for _ in range(2):
            reviewed = review_intake_with_profile_evidence(candidate, self.paths)
            candidate = reviewed['intake']
            self.assertEqual(candidate['transport']['destination'], host)
            self.assertFalse(candidate['transport'].get('km_one_way'))
            self.assertNotEqual(reviewed['status'], 'ready')
            self.assertTrue(any(row['field'] == 'transport.km_one_way' for row in reviewed['questions']))
        self.assertEqual(preflight_intakes([candidate], self.paths)['status'], 'blocked')
        candidate['transport']['km_one_way'] = 31
        answered = review_intake_with_profile_evidence(candidate, self.paths)
        self.assertEqual(answered['intake']['transport']['km_one_way'], 31)

    def test_actual_station_can_use_its_own_known_or_personal_distance(self):
        from honorarios_app.services import review_intake_with_profile_evidence
        host = 'Posto Territorial de Capture City'
        source = 'COMANDO DISTRITAL DE Example City\n' + host + '\nProcesso 710/26.0TSTXX\nServico de interpretacao presencial.'
        for provider, expected in (('personal', 27), ('known', 23)):
            with self.subTest(provider=provider):
                profiles = json.loads(self.paths.personal_profiles.read_text(encoding='utf-8'))
                distances = profiles['profiles'][0]['travel_distances_by_city']
                distances.pop('Capture City', None)
                if provider == 'personal':
                    distances['Capture City'] = expected
                self.paths.personal_profiles.write_text(json.dumps(profiles), encoding='utf-8')
                known = json.loads(self.paths.known_destinations.read_text(encoding='utf-8'))
                if provider == 'known':
                    known.append({'destination': 'Capture City', 'km_one_way': expected, 'institution_examples': [host]})
                self.paths.known_destinations.write_text(json.dumps(known), encoding='utf-8')
                result = self.upload(source_text=source, profile_name='example_interpreting',
                    ai_fields={'service_place': host, 'locality': 'Capture City', 'service_entity': host, 'service_entity_type': 'gnr'})
                self.assertEqual(result['candidate_intake']['transport']['km_one_way'], expected)
                reviewed = review_intake_with_profile_evidence(result['candidate_intake'], self.paths)
                self.assertEqual(reviewed['intake']['transport']['km_one_way'], expected)

    def test_trusted_picker_day_uses_saved_dst_timezone_not_utc_or_filename(self):
        result = self.upload(original_day=None, picker_time="2026-07-01T23:30:00Z", filename="IMG_20260101.jpg")
        self.assertEqual(result["candidate_intake"]["service_date"], "2026-07-02")
        self.assertEqual(result["review"]["status"], "ready")
        self.assertNotIn("visible_metadata_date", result["source"]["metadata"])
        evidence = {row["field"]: row for row in result["source_evidence"]["field_evidence"]}
        self.assertEqual(evidence["photo_metadata_date"]["source"], "google_photos_creation_time")

    def test_missing_picker_timezone_does_not_fall_back_to_renamed_filename(self):
        self.preferences["capture_timezone"] = ""
        result = self.upload(original_day=None, picker_time="2026-07-01T23:30:00Z", filename="IMG_20260101.jpg")
        self.assertFalse(result["candidate_intake"].get("service_date"))
        self.assertNotEqual(result["review"]["status"], "ready")
        self.assertNotIn("visible_metadata_date", result["source"]["metadata"])

    def test_original_vs_picker_date_conflict_blocks_even_with_printed_date_and_policy_disabled(self):
        for date_policy in (True, False):
            with self.subTest(date_policy=date_policy):
                self.preferences["capture_date_is_service_date"] = date_policy
                result = self.upload(original_day="2026:07:01 21:00:00", picker_time="2026-07-01T23:30:00Z",
                    source_extra="Servico realizado em 01/07/2026.", ai_fields={"service_date": "2026-07-01"})
                self.assertEqual(result["source"]["metadata"]["picker_date_conflict"],
                                 {"original_exif": "2026-07-01", "google_photos": "2026-07-02"})
                self.assertNotEqual(result["review"]["status"], "ready")
                self.assertTrue(result["review"].get("questions"))

    def test_picker_capture_date_conflict_can_be_resolved_with_normal_numbered_answer(self):
        from honorarios_app.services import apply_numbered_answers
        self.preferences["capture_date_is_service_date"] = False
        result = self.upload(original_day="2026:07:01 21:00:00", picker_time="2026-07-01T23:30:00Z",
            source_extra="Servico realizado em 01/07/2026.", ai_fields={"service_date": "2026-07-01"})
        date_question = next((row for row in result["review"].get("questions", [])
                              if row["field"] in {"service_date", "service_date_source"}), None)
        self.assertIsNotNone(date_question, "A metadata conflict must expose an answerable date question.")
        answer = f"{date_question['number']}. 2026-07-02"
        updated = apply_numbered_answers({"intake": result["candidate_intake"], "answers": answer}, self.paths)
        self.assertEqual(updated["status"], "ready")
        self.assertEqual(updated["service_date"], "2026-07-02")

    def test_shown_legacy_city_and_police_city_never_supply_capture_city(self):
        result = self.upload(capture_cities=(), shown_city="Capture City", legacy_city="Capture City")
        self.assertNotIn("photo_metadata_city", result["source"]["metadata"])
        self.assertEqual(result["candidate_intake"]["photo_defaults_applied"]["routing_status"], "missing_city")
        self.assertFalse(result["candidate_intake"].get("payment_entity"))
        self.assertNotEqual(result["review"]["status"], "ready")

    def test_conflicting_embedded_capture_cities_pause_before_routing(self):
        result = self.upload(capture_cities=("Capture City", "Other City"))
        self.assertNotIn("photo_metadata_city", result["source"]["metadata"])
        self.assertEqual(result["candidate_intake"]["photo_defaults_applied"]["routing_status"], "ambiguous_city")
        self.assertNotEqual(result["review"]["status"], "ready")
        self.assertFalse(result["candidate_intake"].get("payment_entity"))

    def test_embedded_vs_ai_capture_city_conflict_cannot_silently_choose_a_court(self):
        result = self.upload(ai_fields={"photo_metadata_city": "Other City"})
        self.assertEqual(result["candidate_intake"]["photo_defaults_applied"]["routing_status"], "ambiguous_city")
        self.assertNotEqual(result["review"]["status"], "ready")

    def test_verified_gps_supplies_city_without_fabricating_embedded_name_or_physical_venue(self):
        from honorarios_app.services import review_intake_with_profile_evidence
        self.preferences['verified_gps_areas'] = [verified_area()]
        result = self.upload(capture_cities=())
        metadata, intake = result['source']['metadata'], result['candidate_intake']
        self.assertNotIn('photo_metadata_city', metadata)
        self.assertEqual(metadata['gps_city_match']['city'], 'Capture City')
        self.assertEqual(intake['photo_defaults_applied']['photo_city_source'], 'verified_gps_area')
        self.assertEqual(intake['payment_entity'], 'Tribunal de Capture City')
        self.assertEqual(intake['service_place'], 'Esquadra de Example City')
        self.assertEqual(result['review']['status'], 'ready')
        evidence = {row['field']: row for row in result['source_evidence']['field_evidence']}
        self.assertNotIn('photo_metadata_city', evidence)
        self.assertEqual(evidence['photo_capture_city']['source'], 'verified_gps_area')
        self.assertIn('derived', evidence['payment_entity']['reason'])
        self.assertIn('https://places.example.test/', evidence['photo_gps_city']['excerpt'])
        reviewed = review_intake_with_profile_evidence(intake, self.paths)
        proof = next(row for row in reviewed['review_evidence']['field_evidence'] if row['field'] == 'photo_capture_city')
        self.assertEqual(proof['source'], 'verified_gps_area')
        self.assertEqual(reviewed['status'], 'ready')

    def test_gps_city_conflict_with_embedded_or_ai_requires_one_source_bound_answer(self):
        from honorarios_app.services import apply_numbered_answers
        self.preferences['verified_gps_areas'] = [verified_area()]
        for supplied in ({'capture_cities': ('Other City',)},
                         {'capture_cities': (), 'ai_fields': {'photo_metadata_city': 'Other City'}},
                         {'capture_cities': ('Capture City', 'Other City')}):
            with self.subTest(supplied=supplied):
                result = self.upload(**supplied)
                intake = result['candidate_intake']
                self.assertFalse(intake.get('payment_entity'))
                self.assertEqual(intake['photo_defaults_applied']['routing_status'], 'ambiguous_city')
                self.assertEqual(intake['photo_defaults_applied']['gps_city_status'], 'conflicting_city_evidence')
                question = next(row for row in result['review']['questions'] if row['field'] == 'photo_capture_city')
                updated = apply_numbered_answers({'intake': intake, 'answers': f"{question['number']}. Capture City"}, self.paths)
                self.assertEqual(updated['intake']['payment_entity'], 'Tribunal de Capture City')
                self.assertEqual(updated['intake']['photo_defaults_applied']['photo_city_source'], 'user_confirmed_capture_city')
                self.assertEqual(updated['intake']['photo_capture_city_source_sha256'], result['source']['sha256'])
                self.assertEqual(updated['status'], 'ready')

    def test_enabled_invalid_catalog_or_overlapping_cities_does_not_fall_back_to_embedded_city(self):
        for areas, status in (([verified_area(radius_m=501)], 'invalid_configuration'),
                              ([verified_area(), verified_area(city='Other City')], 'ambiguous')):
            with self.subTest(status=status):
                self.preferences['verified_gps_areas'] = areas
                result = self.upload()
                self.assertEqual(result['source']['metadata']['photo_metadata_city'], 'Capture City')
                self.assertEqual(result['source']['metadata']['gps_city_match']['status'], status)
                self.assertFalse(result['candidate_intake'].get('payment_entity'))
                self.assertTrue(any(row['field'] == 'photo_capture_city' for row in result['review']['questions']))

    def test_gps_outside_verified_area_does_not_choose_nearest_city_or_ask_again_for_embedded_city(self):
        self.preferences['verified_gps_areas'] = [verified_area(latitude=39)]
        result = self.upload(capture_cities=())
        self.assertEqual(result['source']['metadata']['gps_city_match']['status'], 'outside_verified_areas')
        self.assertFalse(result['candidate_intake'].get('payment_entity'))
        self.assertTrue(any(row['field'] == 'photo_capture_city' for row in result['review']['questions']))
        embedded = self.upload()
        self.assertEqual(embedded['candidate_intake']['payment_entity'], 'Tribunal de Capture City')
        self.assertNotEqual(embedded['candidate_intake']['photo_defaults_applied'].get('photo_city_source'), 'verified_gps_area')

    def test_gps_default_keeps_duplicate_stop_and_manual_payer_override(self):
        from honorarios_app.services import review_intake_with_profile_evidence
        self.preferences['verified_gps_areas'] = [verified_area()]
        result = self.upload(capture_cities=())
        intake = deepcopy(result['candidate_intake'])
        intake.update(payment_entity='Manual Court', recipient_email='manual@example.test', review_cleared_fields=['payment_entity'])
        reviewed = review_intake_with_profile_evidence(intake, self.paths)
        self.assertEqual(reviewed['intake']['payment_entity'], 'Manual Court')
        self.paths.duplicate_index.write_text(json.dumps([{'case_number': '710/26.0TSTXX',
            'service_date': '2026-07-02', 'status': 'sent'}]), encoding='utf-8')
        duplicate = self.upload(capture_cities=())
        self.assertEqual(duplicate['review']['status'], 'duplicate')
        self.assertFalse(duplicate['review']['send_allowed'])

    def test_only_missing_physical_venue_answer_fills_saved_trip_and_old_answer_rereview_needs_no_ai(self):
        from honorarios_app.services import apply_numbered_answers, review_intake_with_profile_evidence
        profiles = json.loads(self.paths.personal_profiles.read_text(encoding='utf-8'))
        profiles['profiles'][0]['travel_distances_by_city']['Capture City'] = 31
        self.paths.personal_profiles.write_text(json.dumps(profiles), encoding='utf-8')
        result = self.upload(source_text='Guarda Nacional Republicana\nProcesso 710/26.0TSTXX\nServiço de interpretação presencial.',
            ai_fields={'service_entity': 'Guarda Nacional Republicana', 'service_entity_type': 'gnr', 'service_place': '', 'locality': ''})
        candidate = deepcopy(result['candidate_intake'])
        candidate['transport'] = {'destination': '', 'km_one_way': ''}
        candidate['auto_profile']['auto_applied'] = False
        missing = review_intake_with_profile_evidence(candidate, self.paths)
        question = next(row for row in missing['questions'] if row['field'] == 'service_place')
        venue = 'GNR de Capture City — Unidade de Apoio'
        with patch('honorarios_app.services.recover_source_with_openai', side_effect=AssertionError('Venue answers do not reread photos')):
            answered = apply_numbered_answers({'intake': candidate, 'answers': f"{question['number']}. {venue}"}, self.paths)
            self.assertEqual(answered['status'], 'ready', answered.get('questions'))
            self.assertEqual(answered['effective_intake']['transport']['destination'], 'Capture City')
            self.assertEqual(answered['effective_intake']['transport']['km_one_way'], 31)
            self.assertIn('na GNR de Capture City', answered['draft_text'])
            self.assertEqual(answered['intake']['payment_entity'], 'Tribunal de Capture City')
            old_answer = deepcopy(candidate)
            old_answer.update(service_place=venue, service_place_phrase=f'em diligência realizada em {venue}')
            rereviewed = review_intake_with_profile_evidence(old_answer, self.paths)
            self.assertEqual(rereviewed['status'], 'ready', rereviewed.get('questions'))
            self.assertEqual(rereviewed['effective_intake']['transport']['km_one_way'], 31)
            self.assertIn('na GNR de Capture City', rereviewed['draft_text'])
            for km, clears in ((37, []), ('', ['transport.km_one_way'])):
                edited = deepcopy(old_answer)
                edited['transport']['km_one_way'] = km
                edited['review_cleared_fields'] = clears
                kept = review_intake_with_profile_evidence(edited, self.paths)
                self.assertEqual((kept.get('effective_intake') or kept['intake'])['transport']['km_one_way'], km)


if __name__ == "__main__":
    unittest.main()
