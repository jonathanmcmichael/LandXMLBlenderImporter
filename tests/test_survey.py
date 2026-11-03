import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "landxml_importer"))

from survey import (
    parse_coordinate, resolve_crs_entry, search_us_nad83_crs,
    survey_reference, us_nad83_crs_items,
)
from pyproj import CRS


class SurveyReferenceTests(unittest.TestCase):
    def test_search_by_zone_tokens_and_epsg(self):
        matches = search_us_nad83_crs("colorado central ftUS")
        self.assertEqual(len(matches), 1)
        self.assertIn("EPSG:2232", matches[0][0])
        self.assertEqual(search_us_nad83_crs("2232"), matches)
        self.assertEqual(len(search_us_nad83_crs("")), len(us_nad83_crs_items()) - 1)
        self.assertEqual(search_us_nad83_crs("not a real zone"), ())

    def test_editable_crs_entry_resolves_names_codes_and_manual_compatibility(self):
        for text in (
            "2232", "EPSG:2232", " epsg:2232 ", "NAD83 / Colorado Central (ftUS)",
            "NAD83 / Colorado Central (ftUS) - EPSG:2232",
        ):
            with self.subTest(text=text):
                self.assertEqual(resolve_crs_entry(text, "4326"), "2232")
        self.assertEqual(resolve_crs_entry("EPSG:6428"), "6428")
        self.assertEqual(resolve_crs_entry(""), "")
        self.assertEqual(resolve_crs_entry("CUSTOM", "2232"), "2232")
        for text in ("Colorado", "EPSG:", "invalid"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                resolve_crs_entry(text)

    def test_us_nad83_dropdown_catalog(self):
        items = us_nad83_crs_items()
        self.assertIs(items, us_nad83_crs_items())
        self.assertEqual(items[0][0], "CUSTOM")
        codes = [item[0] for item in items]
        self.assertEqual(len(codes), len(set(codes)))
        labels = {code: label for code, label, _ in items}
        self.assertIn("Colorado Central (ftUS)", labels["2232"])
        self.assertIn("Colorado Central", labels["26954"])
        self.assertIn("UTM zone 13N", labels["26913"])
        self.assertNotIn("4326", codes)
        self.assertIn("26986", codes)
        self.assertNotIn("32198", codes)  # NAD83 / Quebec Lambert is not a US CRS.
        for code, label, description in items[1:]:
            with self.subTest(code=code):
                crs = CRS.from_epsg(code)
                self.assertTrue(crs.is_projected)
                self.assertTrue(crs.name.startswith("NAD83 /"))
                self.assertIn(f"EPSG:{code}", label)
                self.assertTrue("United States" in description or "USA" in description)

    def reference(self, origin=(3000000.0, 1698067.4612223296, 5000.0), **kwargs):
        return survey_reference(
            origin, source_units="US_SURVEY_FEET", unit_to_meters=1200 / 3937, **kwargs,
        )

    def test_colorado_central_central_meridian_and_standard_parallel(self):
        reference = self.reference(horizontal_epsg="2232")
        anchor = reference["cesium_anchor"]
        self.assertAlmostEqual(anchor["longitude_degrees"], -105.5, places=7)
        self.assertAlmostEqual(anchor["latitude_degrees"], 39.75, places=7)
        self.assertIsNone(anchor["ellipsoid_height_meters"])
        self.assertEqual(reference["origin"]["elevation"], 5000.0)
        self.assertEqual(reference["local_axes"], ["grid_east", "grid_north", "up"])
        self.assertTrue(reference["warnings"])
        self.assertIn("reported_accuracy_meters", reference["horizontal_operation"])
        self.assertEqual(json.loads(json.dumps(reference, allow_nan=False)), reference)

    def test_us_survey_feet_are_converted_to_metric_crs_units(self):
        feet = self.reference(horizontal_epsg="2232")
        meters = self.reference(horizontal_epsg="26954")
        for key in ("longitude_degrees", "latitude_degrees"):
            self.assertAlmostEqual(feet["cesium_anchor"][key], meters["cesium_anchor"][key], delta=1e-8)

    def test_explicit_ellipsoid_height_is_not_source_elevation(self):
        reference = self.reference(
            horizontal_epsg="EPSG:2232", vertical_datum="NAVD88", ellipsoid_height="1490.123456",
        )
        self.assertEqual(reference["vertical_datum"], "NAVD88")
        self.assertEqual(reference["cesium_anchor"]["ellipsoid_height_meters"], 1490.123456)
        self.assertEqual(reference["cesium_anchor"]["height_datum"], "WGS84 ellipsoid")

    def test_missing_crs_preserves_pivot_but_does_not_invent_anchor(self):
        reference = self.reference()
        self.assertIsNone(reference["horizontal_crs"])
        self.assertIsNone(reference["cesium_anchor"])
        self.assertEqual(reference["vertical_datum"], "unknown")

    def test_invalid_crs_and_coordinate_inputs_fail(self):
        for epsg in ("4326", "4978", "invalid", "0"):
            with self.subTest(epsg=epsg), self.assertRaises(ValueError):
                self.reference(horizontal_epsg=epsg)
        for value in ("nan", "inf", "-inf", "not a coordinate"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_coordinate(value)
        with self.assertRaises(ValueError):
            self.reference((math.nan, 0, 0))
        with self.assertRaises(ValueError):
            self.reference(ellipsoid_height="100")
        with self.assertRaises(ValueError):
            self.reference(horizontal_epsg="2232", ellipsoid_height="nan")

    def test_wrong_state_plane_zone_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "area of use"):
            self.reference((0, 0, 0), horizontal_epsg="2232")

    def test_pivot_input_retains_double_precision(self):
        self.assertEqual(parse_coordinate("3000000.123456789"), 3000000.123456789)


if __name__ == "__main__":
    unittest.main()
