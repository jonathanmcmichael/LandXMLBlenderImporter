from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "landxml_importer"))

from landxml import build_mesh_data, parse_landxml, shared_origin  # noqa: E402


class LandXMLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = REPO_ROOT / "tests" / "fixtures" / "two_surfaces.xml"
        cls.surfaces = parse_landxml(fixture)

    def test_preserves_surfaces_points_and_authoritative_faces(self):
        self.assertEqual([surface.name for surface in self.surfaces], ["Existing Ground", "Finished Ground"])
        self.assertEqual(self.surfaces[0].points["1"], (2000.0, 1000.0, 10.0))
        self.assertEqual(self.surfaces[0].faces, (("1", "2", "3"),))

    def test_invalid_point_reference_is_skipped_and_counted(self):
        self.assertEqual(self.surfaces[1].faces, (("1", "2", "3"),))
        self.assertEqual(self.surfaces[1].skipped_face_count, 1)

    def test_shared_origin_retains_surface_offset(self):
        origin = shared_origin(self.surfaces)
        first = build_mesh_data(self.surfaces[0], origin=origin)
        second = build_mesh_data(self.surfaces[1], origin=origin)
        self.assertEqual(origin, (2000.0, 1000.0, 0.0))
        self.assertEqual(first.vertices[0], (0.0, 0.0, 10.0))
        self.assertEqual(second.vertices[0], (200.0, 100.0, 20.0))

    def test_international_feet_convert_to_meters(self):
        mesh = build_mesh_data(
            self.surfaces[0],
            origin=(2000.0, 1000.0, 0.0),
            source_units="INTERNATIONAL_FEET",
        )
        self.assertAlmostEqual(mesh.vertices[1][0], 3.048)
        self.assertAlmostEqual(mesh.vertices[2][1], 3.048)
        self.assertAlmostEqual(mesh.vertices[0][2], 3.048)


if __name__ == "__main__":
    unittest.main()
