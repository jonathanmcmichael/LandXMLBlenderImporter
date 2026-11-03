import json
from pathlib import Path
import sys
import types
import unittest

from pyproj import Transformer
from shapely import union_all
from shapely.geometry import Polygon, shape


# Load the pure geometry modules without executing Blender's package initializer.
package = types.ModuleType("_landxml_core")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "landxml_importer")]
sys.modules.setdefault("_landxml_core", package)
from _landxml_core.footprint import surface_footprint


class FootprintTests(unittest.TestCase):
    def export(self, vertices, faces, **overrides):
        options = {
            "origin": (3000000, 1698067.4612223296, 5000),
            "unit_to_meters": 1200 / 3937,
            "horizontal_epsg": "2232",
            "name": "Test",
        }
        options.update(overrides)
        return surface_footprint(vertices, faces, **options)

    def donut_and_island(self):
        vertices, faces = [], []
        for x, y in ((0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2), (2, 2), (5, 0)):
            index = len(vertices)
            vertices.extend(((x, y, 0), (x + 1, y, 0), (x + 1, y + 1, 0), (x, y + 1, 0)))
            faces.extend(((index, index + 1, index + 2), (index, index + 2, index + 3)))
        return vertices, faces

    def test_exact_footprint_has_hole_and_separate_island(self):
        vertices, faces = self.donut_and_island()
        result = self.export(vertices, faces)
        self.assertEqual(result["landxml"]["island_count"], 2)
        self.assertEqual(result["landxml"]["hole_count"], 1)
        self.assertEqual(result["landxml"]["area_square_meters"], 9)
        geographic = union_all([shape(feature["geometry"]) for feature in result["features"]])
        parts = [Polygon(piece["ring"]) for piece in result["cesium_unreal"]["pieces"]]
        self.assertTrue(union_all(parts).equals(geographic))
        self.assertEqual(sum(len(polygon.interiors) for polygon in geographic.geoms), 1)
        for feature in result["features"]:
            for ring in feature["geometry"]["coordinates"]:
                self.assertEqual(ring[0], ring[-1])
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

    def test_coordinate_conversion_includes_origin_and_source_units(self):
        result = self.export([(0, 0, 0), (10, 0, 0), (0, 10, 0)], [(0, 1, 2)])
        ring = result["features"][0]["geometry"]["coordinates"][0]
        self.assertAlmostEqual(ring[0][0], -105.5, places=7)
        self.assertAlmostEqual(ring[0][1], 39.75, places=7)
        transform = Transformer.from_crs(2232, 4326, always_xy=True)
        expected = transform.transform(3000000 + 10 / (1200 / 3937), 1698067.4612223296)
        self.assertAlmostEqual(ring[1][0], expected[0], places=10)
        self.assertAlmostEqual(ring[1][1], expected[1], places=10)

    def test_duplicate_faces_do_not_add_area_or_duplicate_polygons(self):
        result = self.export([(0, 0, 0), (10, 0, 0), (0, 10, 0)], [(0, 1, 2), (2, 1, 0)])
        self.assertEqual(result["landxml"]["area_square_meters"], 50)
        self.assertEqual(result["cesium_unreal"]["piece_count"], 1)

    def test_no_visible_faces_invalid_faces_and_missing_crs_fail(self):
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        for faces in ([], [(0, 0, 0)], [(0, 1, 3)], [(0, 1)]):
            with self.subTest(faces=faces), self.assertRaises(ValueError):
                self.export(vertices, faces)
        with self.assertRaises(ValueError):
            self.export(vertices, [(0, 1, 2)], horizontal_epsg="")
        with self.assertRaises(ValueError):
            self.export(vertices, [(0, 1, 2)], horizontal_epsg="4326")
        with self.assertRaises(ValueError):
            self.export([(float("nan"), 0, 0), *vertices], [(1, 2, 3)])


if __name__ == "__main__":
    unittest.main()
