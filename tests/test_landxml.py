from pathlib import Path
import json
import math
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "landxml_importer"))

from landxml import (  # noqa: E402
    LandXMLError,
    build_mesh_data,
    build_curve_data,
    build_point_data,
    geometry_fingerprint,
    parse_landxml,
    parse_landxml_document,
    resolve_source_units,
    shared_document_origin,
    match_breakline_mesh_edges,
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

    def test_document_model_preserves_non_surface_records_and_units(self):
                document = self._parse_document(
                        """
                        <Units><Imperial linearUnit="foot" /></Units>
                        <Project name="Campus" />
                        <SourceData><Boundaries><Boundary bndType="outer" edgeTrim="true">
                            <PntList3D>0 0 0 1 0 0 1 1 0</PntList3D>
                        </Boundary></Boundaries><Breaklines>
                            <Breakline brkType="standard"><PntList3D>0 0 0 1 1 0</PntList3D></Breakline>
                        </Breaklines></SourceData>
                        <Surfaces><Surface name="Test"><Definition>
                            <Pnts><P id="a">0 0 0</P><P id="b">0 1 0</P><P id="c">1 0 0</P></Pnts>
                            <Faces><F>a b c</F></Faces>
                        </Definition></Surface></Surfaces>
                        """
                )
                flattened = json.dumps(document.root.to_dict())
                streamed = "".join(document.root.iter_json_chunks())
                self.assertEqual(document.declared_linear_unit, "foot")
                self.assertEqual(document.source_units, "US_SURVEY_FEET")
                self.assertIsNotNone(document.unit_warning)
                self.assertEqual(len(document.surfaces), 1)
                self.assertIn('"name": "Project"', flattened)
                self.assertIn('"name": "Boundary"', flattened)
                self.assertIn('"edgeTrim": "true"', flattened)
                self.assertIn('"name": "Breakline"', flattened)
                self.assertIn('"brkType": "standard"', flattened)
                self.assertEqual(json.loads(streamed), document.root.to_dict())

    def test_plan_feature_lines_and_arcs_become_one_curve_record(self):
                document = self._parse_document(
                        """
                        <PlanFeatures><PlanFeature name="Campus Edge">
                            <CoordGeom><Line><Start>0 0 0</Start><End>0 2 0</End></Line>
                                <Curve rot="ccw" radius="2"><Start>0 2 0</Start><Center>0 0</Center><End>2 0 2</End></Curve>
                            </CoordGeom><Feature code="FeatureLine"><Property label="layer" value="C-TOPO-FEAT" /></Feature>
                        </PlanFeature></PlanFeatures>
                        """
                )
                feature = next(curve for curve in document.curves if curve.category == "PlanFeature")
                converted = build_curve_data(feature, source_units="INTERNATIONAL_FEET")
                self.assertEqual(feature.name, "Campus Edge")
                self.assertEqual(len(feature.points), 20)
                self.assertEqual(feature.properties, (("layer", "C-TOPO-FEAT"),))
                self.assertAlmostEqual(converted.points[-1][2], 0.6096)

    def test_unit_resolution_supports_override_and_ambiguous_foot_warning(self):
                self.assertEqual(resolve_source_units("meter"), ("METERS", None))
                self.assertEqual(resolve_source_units("foot", "INTERNATIONAL_FEET"), ("INTERNATIONAL_FEET", None))
                source_units, warning = resolve_source_units("foot")
                self.assertEqual(source_units, "US_SURVEY_FEET")
                self.assertIsNotNone(warning)

    def test_cgpoint_records_are_mapped_to_blender_points(self):
        document = self._parse_document(
            """
            <CgPoints><CgPoint name="survey-1" desc="control">100 200 3</CgPoint></CgPoints>
            <Surfaces><Surface name="Test"><Definition>
              <Pnts><P id="1">0 0 0</P><P id="2">0 1 0</P><P id="3">1 0 0</P></Pnts>
              <Faces><F>1 2 3</F></Faces>
            </Definition></Surface></Surfaces>
            """
        )
        point_data = build_point_data(document.points, origin=(200.0, 100.0, 0.0), source_units="INTERNATIONAL_FEET")
        self.assertEqual(len(document.points), 1)
        self.assertEqual(dict(document.points[0].attributes)["name"], "survey-1")
        self.assertAlmostEqual(point_data.coordinates[0][0], 0.0)
        self.assertAlmostEqual(point_data.coordinates[0][1], 0.0)
        self.assertAlmostEqual(point_data.coordinates[0][2], 0.9144)

    def test_two_dimensional_cgpoint_defaults_elevation_to_zero(self):
        document = self._parse_document(
            """
            <CgPoints><CgPoint name="survey-2">101 201</CgPoint></CgPoints>
            """
        )
        self.assertEqual(document.points[0].coordinate, (201.0, 101.0, 0.0))

    def test_document_with_only_cgpoints_has_shared_origin(self):
        document = self._parse_document(
            """
            <CgPoints><CgPoint name="survey-1">100 200 3</CgPoint></CgPoints>
            """
        )
        self.assertEqual(shared_document_origin(document), (200.0, 100.0, 0.0))

    def test_metadata_only_document_has_zero_origin(self):
        document = self._parse_document("<Project name='Campus' />")
        self.assertEqual(shared_document_origin(document), (0.0, 0.0, 0.0))

    def test_planfeature_locations_become_categorized_points(self):
        document = self._parse_document(
            """
            <PlanFeatures><PlanFeature name="curb"><Location desc="elevation point">100 200 3</Location></PlanFeature></PlanFeatures>
            """
        )
        location = next(point for point in document.points if point.category == "Location")
        point_data = build_point_data((location,))
        self.assertEqual(location.coordinate, (200.0, 100.0, 3.0))
        self.assertEqual(point_data.category, "Location")
        self.assertEqual(dict(location.attributes)["desc"], "elevation point")

    def test_pipe_centerline_resolves_point_references_and_coordinates(self):
                document = self._parse_document(
                        """
                        <PipeNetworks><PipeNetwork name="storm" pipeNetType="storm">
                            <Structs>
                                <Struct name="node-a"><Center>100 200 3</Center><Invert refPipe="pipe-1" elev="2" /></Struct>
                                <Struct name="node-b"><Center>102 202</Center><Invert refPipe="pipe-1" elev="1" /></Struct>
                            </Structs>
                            <Pipes><Pipe name="pipe-1" refStart="node-a" refEnd="node-b" /></Pipes>
                        </PipeNetwork></PipeNetworks>
                        """
                )
                pipe = next(curve for curve in document.curves if curve.category == "Pipe")
                self.assertEqual(pipe.name, "pipe-1")
                self.assertEqual(pipe.points, ((200.0, 100.0, 2.0), (202.0, 102.0, 1.0)))
                structures = [point for point in document.points if point.category == "Struct"]
                self.assertEqual(len(structures), 2)
                self.assertEqual(dict(structures[0].attributes)["Invert_elev"], "2")

    def test_profiles_and_cross_sections_keep_local_station_coordinates(self):
                document = self._parse_document(
                        """
                        <Alignments><Alignment name="Road A"><Profile name="Design">
                            <ProfAlign name="Finished Grade"><PVI>0 100</PVI><PVI>20 101</PVI></ProfAlign>
                        </Profile></Alignment></Alignments>
                        <CrossSects><CrossSect sta="12.5"><CrossSectSurf name="Existing Ground">
                            <PntList2D>-3 1 3 2</PntList2D>
                        </CrossSectSurf></CrossSect></CrossSects>
                        """
                )
                profile = next(curve for curve in document.curves if curve.category == "Profile")
                section = next(curve for curve in document.curves if curve.category == "CrossSectSurf")
                profile_data = build_curve_data(profile, origin=(500, 500, 0), source_units="INTERNATIONAL_FEET")
                section_data = build_curve_data(section, origin=(500, 500, 0), source_units="INTERNATIONAL_FEET")
                self.assertEqual(profile.points, ((0.0, 0.0, 100.0), (20.0, 0.0, 101.0)))
                self.assertEqual(section.points, ((-3.0, 12.5, 1.0), (3.0, 12.5, 2.0)))
                self.assertAlmostEqual(profile_data.points[1][0], 6.096)
                self.assertAlmostEqual(section_data.points[0][0], -0.9144)
                self.assertAlmostEqual(section_data.points[0][1], 3.81)

    def test_outer_boundary_clips_faces_across_concave_gulf(self):
                document = self._parse_document(
                        """
                        <SourceData><Boundaries><Boundary bndType="outer" edgeTrim="true">
                            <PntList3D>0 0 0 0 4 0 4 4 4 4 3 4 1 3 1 1 1 1 4 1 4 4 0 4 0 0 0</PntList3D>
                        </Boundary></Boundaries></SourceData>
                        <Surfaces><Surface name="Test"><Definition>
                            <Pnts><P id="1">0 0 0</P><P id="2">0 4 0</P><P id="3">4 4 4</P><P id="4">4 0 4</P></Pnts>
                            <Faces><F>1 2 3</F><F>1 3 4</F></Faces>
                        </Definition></Surface></Surfaces>
                        """
                )
                mesh = build_mesh_data(document.surfaces[0])
                from shapely.geometry import Polygon

                boundary = Polygon([(east, north) for east, north, _ in document.surfaces[0].boundaries[0].points])
                output_triangles = [
                        Polygon([(mesh.vertices[index][0], mesh.vertices[index][1]) for index in face])
                        for face in mesh.faces
                ]
                self.assertEqual(mesh.source_face_count, 2)
                self.assertEqual(mesh.boundary_clipped_face_count, 2)
                self.assertGreater(len(mesh.faces), mesh.source_face_count)
                self.assertAlmostEqual(sum(triangle.area for triangle in output_triangles), boundary.area)
                self.assertTrue(all(boundary.covers(triangle) for triangle in output_triangles))
                self.assertTrue(all(math.isclose(z, y, abs_tol=1e-9) for _, y, z in mesh.vertices))

    def test_hide_boundary_removes_interior_faces(self):
                document = self._parse_document(
                        """
                        <SourceData><Boundaries>
                            <Boundary bndType="outer" edgeTrim="true"><PntList3D>0 0 0 0 10 0 10 10 10 10 0 10 0 0 0</PntList3D></Boundary>
                            <Boundary bndType="hide" edgeTrim="true"><PntList3D>4 4 4 4 6 4 6 6 6 6 4 6 4 4 4</PntList3D></Boundary>
                        </Boundaries></SourceData>
                        <Surfaces><Surface name="Test"><Definition>
                            <Pnts><P id="1">0 0 0</P><P id="2">0 10 0</P><P id="3">10 10 10</P><P id="4">10 0 10</P></Pnts>
                            <Faces><F>1 2 3</F><F>1 3 4</F></Faces>
                        </Definition></Surface></Surfaces>
                        """
                )
                mesh = build_mesh_data(document.surfaces[0])
                from shapely.geometry import Polygon

                expected = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], holes=[[(4, 4), (6, 4), (6, 6), (4, 6)]])
                triangles = [
                        Polygon([(mesh.vertices[index][0], mesh.vertices[index][1]) for index in face])
                        for face in mesh.faces
                ]
                self.assertAlmostEqual(sum(triangle.area for triangle in triangles), expected.area)
                self.assertTrue(all(expected.covers(triangle) for triangle in triangles))

    def test_boundaries_attach_to_their_enclosing_surface(self):
        document = self._parse_document(
            """
            <Surfaces>
              <Surface name="Trimmed"><SourceData><Boundaries>
                <Boundary bndType="outer" edgeTrim="true"><PntList3D>0 0 0 0 2 0 2 2 0 2 0 0 0 0 0</PntList3D></Boundary>
              </Boundaries></SourceData><Definition>
                <Pnts><P id="1">0 0 0</P><P id="2">0 4 0</P><P id="3">4 4 0</P><P id="4">4 0 0</P></Pnts>
                <Faces><F>1 2 3</F><F>1 3 4</F></Faces>
              </Definition></Surface>
              <Surface name="Untrimmed"><Definition>
                <Pnts><P id="1">0 0 0</P><P id="2">0 4 0</P><P id="3">4 4 0</P></Pnts>
                <Faces><F>1 2 3</F></Faces>
              </Definition></Surface>
            </Surfaces>
            """
        )
        trimmed, untrimmed = document.surfaces
        self.assertEqual(len(trimmed.boundaries), 1)
        self.assertEqual(untrimmed.boundaries, ())
        self.assertGreater(build_mesh_data(trimmed).boundary_clipped_face_count, 0)

    def test_unowned_boundary_with_multiple_surfaces_raises(self):
        with self.assertRaises(LandXMLError):
            self._parse_document(
                """
                <SourceData><Boundaries><Boundary bndType="outer" edgeTrim="true">
                  <PntList3D>0 0 0 0 2 0 2 2 0 0 0 0</PntList3D>
                </Boundary></Boundaries></SourceData>
                <Surfaces>
                  <Surface name="A"><Definition><Pnts><P id="1">0 0 0</P><P id="2">0 1 0</P><P id="3">1 0 0</P></Pnts><Faces><F>1 2 3</F></Faces></Definition></Surface>
                  <Surface name="B"><Definition><Pnts><P id="1">0 0 0</P><P id="2">0 1 0</P><P id="3">1 0 0</P></Pnts><Faces><F>1 2 3</F></Faces></Definition></Surface>
                </Surfaces>
                """
            )

    def test_irregular_line_becomes_curve(self):
        document = self._parse_document(
            """
            <PlanFeatures><PlanFeature name="Swale"><CoordGeom>
              <IrregularLine><PntList3D>0 0 0 1 1 1 2 0 2</PntList3D></IrregularLine>
            </CoordGeom></PlanFeature></PlanFeatures>
            """
        )
        feature = next(curve for curve in document.curves if curve.category == "PlanFeature")
        self.assertEqual(feature.points, ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.0, 2.0, 2.0)))

    def test_line_missing_end_raises_landxml_error(self):
        with self.assertRaises(LandXMLError):
            self._parse_document(
                """
                <PlanFeatures><PlanFeature name="Broken"><CoordGeom>
                  <Line><Start>0 0 0</Start></Line>
                </CoordGeom></PlanFeature></PlanFeatures>
                """
            )

    def test_non_finite_surface_point_is_skipped(self):
        document = self._parse_document(
            """
            <Surfaces><Surface name="Test"><Definition>
              <Pnts><P id="1">0 0 0</P><P id="2">0 1 nan</P><P id="3">1 0 0</P><P id="4">1 1 0</P></Pnts>
              <Faces><F>1 2 3</F><F>1 4 3</F></Faces>
            </Definition></Surface></Surfaces>
            """
        )
        surface = document.surfaces[0]
        self.assertNotIn("2", surface.points)
        self.assertEqual(surface.faces, (("1", "4", "3"),))
        self.assertEqual(dict(surface.skipped_face_reasons), {"missing_point": 1})

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

    def test_breakline_segments_match_mesh_edges_with_tolerance(self):
        vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0))
        edges = ((0, 1), (1, 2), (2, 3), (3, 0), (0, 2))
        segments = (
            ((0.00001, 0.0, 0.0), (1.00001, 0.0, 0.0)),
            ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            ((0.0, 0.0, 0.0), (0.5, 0.5, 0.0)),
        )
        edge_indices, matched, total = match_breakline_mesh_edges(vertices, edges, segments)
        self.assertEqual(edge_indices, (0, 3))
        self.assertEqual((matched, total), (2, 3))

    def _parse_single_surface(self, contents):
        document = f"<LandXML><Surfaces><Surface name='Test'><Definition>{contents}</Definition></Surface></Surfaces></LandXML>"
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as file:
            file.write(document)
            path = Path(file.name)
        try:
            return parse_landxml(path)[0]
        finally:
            path.unlink()

    def _parse_document(self, contents):
        document = f"<LandXML>{contents}</LandXML>"
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as file:
            file.write(document)
            path = Path(file.name)
        try:
            return parse_landxml_document(path)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
