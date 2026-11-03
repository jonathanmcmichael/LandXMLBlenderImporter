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

    def test_inward_offset_and_simplify_stay_inside_exact_tin(self):
        # A jagged 100 m square: sawtooth bottom edge with 0.2 m teeth.
        vertices = [(x, 0.2 * (x % 2), 0) for x in range(101)] + [(100, 100, 0), (0, 100, 0)]
        apex = len(vertices)
        vertices.append((50, 50, 0))
        faces = [(i, i + 1, apex) for i in range(100)] + [(100, 101, apex), (101, 102, apex), (102, 0, apex)]
        exact = self.export(vertices, faces)
        result = self.export(vertices, faces, edge_offset_meters=-1.0, simplify_meters=0.5)
        info = result["landxml"]
        self.assertLess(info["boundary_vertex_count"], exact["landxml"]["boundary_vertex_count"] / 10)
        self.assertLess(info["area_square_meters"], info["exact_area_square_meters"])
        self.assertEqual((info["edge_offset_meters"], info["simplify_meters"]), (-1.0, 0.5))
        self.assertTrue(shape(exact["features"][0]["geometry"]).contains(shape(result["features"][0]["geometry"])))
        self.assertIn("no longer the exact TIN edge", " ".join(info["warnings"]))

    def test_outward_offset_grows_and_offset_can_remove_small_islands(self):
        vertices, faces = self.donut_and_island()
        grown = self.export(vertices, faces, edge_offset_meters=0.25)
        self.assertGreater(grown["landxml"]["area_square_meters"], 9)
        # A 10 m square plus a 0.5 m island: a 0.3 m inward offset removes only the island.
        vertices = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (20, 0, 0), (20.5, 0, 0), (20.5, 0.5, 0)]
        shrunk = self.export(vertices, [(0, 1, 2), (0, 2, 3), (4, 5, 6)], edge_offset_meters=-0.3)
        self.assertEqual(shrunk["landxml"]["island_count"], 1)
        self.assertEqual(shrunk["landxml"]["exact_island_count"], 2)
        self.assertIn("changed the island count", " ".join(shrunk["landxml"]["warnings"]))
        parts = union_all([Polygon(piece["ring"]) for piece in shrunk["cesium_unreal"]["pieces"]])
        self.assertTrue(parts.equals(union_all([shape(f["geometry"]) for f in shrunk["features"]])))

    def test_invalid_offset_and_simplify_fail(self):
        vertices, faces = [(0, 0, 0), (10, 0, 0), (0, 10, 0)], [(0, 1, 2)]
        for options in (
            {"edge_offset_meters": float("nan")},
            {"simplify_meters": -1.0},
            {"edge_offset_meters": -10.0},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.export(vertices, faces, **options)

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
