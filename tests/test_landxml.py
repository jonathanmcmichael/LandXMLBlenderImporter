from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "landxml_importer"))

from landxml import (  # noqa: E402
    LandXMLError,
    build_mesh_data,
    geometry_fingerprint,
    parse_landxml,
    shared_origin,
)


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

    def test_easting_northing_point_order_swaps_coordinates(self):
        fixture = REPO_ROOT / "tests" / "fixtures" / "two_surfaces.xml"
        surfaces = parse_landxml(fixture, point_order="ENZ")
        # Point "1" text is "1000 2000 10"; NEZ reads (E=2000, N=1000), ENZ reads (E=1000, N=2000).
        self.assertEqual(surfaces[0].points["1"], (1000.0, 2000.0, 10.0))

    def test_unsupported_point_order_raises(self):
        fixture = REPO_ROOT / "tests" / "fixtures" / "two_surfaces.xml"
        with self.assertRaises(LandXMLError):
            parse_landxml(fixture, point_order="ZZZ")

    def test_custom_origin_offsets_all_coordinates(self):
        mesh = build_mesh_data(
            self.surfaces[0],
            origin=(1990.0, 990.0, 5.0),
        )
        self.assertEqual(mesh.vertices[0], (10.0, 10.0, 5.0))

    def test_non_triangular_face_is_skipped_without_truncation(self):
        surface = self._parse_single_surface(
            """
            <P id="1">0 0 0</P><P id="2">0 1 0</P>
            <P id="3">1 1 0</P><P id="4">1 0 0</P>
            <F>1 2 3 4</F>
            <F>1 2 3</F>
            """
        )
        self.assertEqual(surface.faces, (("1", "2", "3"),))
        self.assertEqual(surface.skipped_face_count, 1)
        self.assertEqual(surface.skipped_face_reasons, (("non_triangular", 1),))

    def test_missing_point_face_reports_skip_reason(self):
        surface = self._parse_single_surface(
            """
            <P id="1">0 0 0</P><P id="2">0 1 0</P><P id="3">1 1 0</P>
            <F>1 2 missing</F><F>1 2 3</F>
            """
        )
        self.assertEqual(surface.faces, (("1", "2", "3"),))
        self.assertEqual(surface.skipped_face_reasons, (("missing_point", 1),))

    def test_degenerate_face_is_retained_and_reported(self):
        surface = self._parse_single_surface(
            """
            <P id="1">0 0 0</P><P id="2">0 1 0</P><P id="3">0 2 0</P>
            <F>1 2 3</F>
            """
        )
        mesh = build_mesh_data(surface)
        self.assertEqual(mesh.faces, ((0, 1, 2),))
        self.assertEqual(mesh.degenerate_face_count, 1)

    def test_geometry_fingerprint_detects_geometry_change(self):
        mesh = build_mesh_data(self.surfaces[0])
        fingerprint = geometry_fingerprint(mesh.vertices, mesh.faces)
        changed_vertices = list(mesh.vertices)
        changed_vertices[0] = (1.0, 2.0, 3.0)
        self.assertNotEqual(fingerprint, geometry_fingerprint(changed_vertices, mesh.faces))
        self.assertEqual(fingerprint, geometry_fingerprint(mesh.vertices, mesh.faces))

    def _parse_single_surface(self, contents):
        document = f"<LandXML><Surfaces><Surface name='Test'><Definition>{contents}</Definition></Surface></Surfaces></LandXML>"
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as file:
            file.write(document)
            path = Path(file.name)
        try:
            return parse_landxml(path)[0]
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
