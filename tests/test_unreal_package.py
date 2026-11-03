import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class Rotator:
    def __init__(self, roll=0.0, pitch=0.0, yaw=0.0):
        self.roll, self.pitch, self.yaw = roll, pitch, yaw

    def quaternion(self):
        return ("quat", self.yaw)


class UnrealPackageHelperTests(unittest.TestCase):
    def setUp(self):
        self.editor = MagicMock()
        self.mesh_actor = MagicMock()
        self.polygon_actor = MagicMock()
        self.editor.spawn_actor_from_object.return_value = self.mesh_actor
        self.editor.spawn_actor_from_class.return_value = self.polygon_actor

        class Georeference:
            def transform_longitude_latitude_height_position_to_unreal(self, vector):
                return vector

        class StaticMesh:
            def get_name(self):
                return "FG-WDC1"

            def get_editor_property(self, name):
                return None

        self.georeference = Georeference()
        self.mesh = StaticMesh()
        self.editor.get_selected_level_actors.return_value = [self.georeference]
        self.import_task = MagicMock()
        self.import_task.get_editor_property.return_value = ["/Game/LandXML/FG-WDC1.FG-WDC1"]
        self.anchor_class = type("Anchor", (), {})
        self.unreal = types.SimpleNamespace(
            EditorActorSubsystem=object,
            SubobjectDataSubsystem=object,
            CesiumGeoreference=Georeference,
            CesiumCartographicPolygon=type("Polygon", (), {}),
            CesiumGlobeAnchorComponent=self.anchor_class,
            SplineComponent=type("Spline", (), {}),
            StaticMesh=StaticMesh,
            Vector=lambda x=0, y=0, z=0: types.SimpleNamespace(x=x, y=y, z=z),
            Rotator=Rotator,
            SplineCoordinateSpace=types.SimpleNamespace(WORLD="world"),
            SplinePointType=types.SimpleNamespace(LINEAR="linear"),
            FBXImportType=types.SimpleNamespace(FBXIT_STATIC_MESH="static"),
            CollisionTraceFlag=types.SimpleNamespace(CTF_USE_COMPLEX_AS_SIMPLE="complex"),
            AssetImportTask=lambda: self.import_task,
            FbxImportUI=MagicMock,
            AssetToolsHelpers=MagicMock(),
            AddNewSubobjectParams=MagicMock(),
            load_asset=lambda path: self.mesh,
            get_editor_subsystem=lambda cls: self.editor,
            get_engine_subsystem=lambda cls: MagicMock(add_new_subobject=MagicMock(return_value=(None, ""))),
            ScopedEditorTransaction=MagicMock(),
            log_warning=MagicMock(),
        )
        self.modules = patch.dict(sys.modules, {"unreal": self.unreal})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        sys.modules.pop("import_cesium_polygons", None)
        spec = importlib.util.spec_from_file_location("_unreal_package_helper", SCRIPTS / "import_landxml_unreal.py")
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)
        self.addCleanup(sys.modules.pop, "import_cesium_polygons", None)

    def write_package(self, directory, *, height=None, fbx=True, **survey_overrides):
        directory = Path(directory)
        if fbx:
            (directory / "site.fbx").write_bytes(b"fbx")
        (directory / "site_FG.footprint.geojson").write_text(json.dumps({
            "landxml": {"format": "landxml-cesium-footprint-v1", "surface": "FG"},
            "cesium_unreal": {"pieces": [{"ring": [[-91.2, 38.8], [-91.1, 38.8], [-91.2, 38.9], [-91.2, 38.8]]}]},
        }))
        survey = {
            "format": "landxml-survey-reference-v1",
            "cesium_anchor": {
                "longitude_degrees": -91.18329928490297,
                "latitude_degrees": 38.82478672628238,
                "ellipsoid_height_meters": height,
            },
            "projection": {"meridian_convergence_degrees": -0.4284007486780979},
            "package": {
                "fbx": "site.fbx",
                "mesh_objects": ["FG-WDC1"],
                "footprints": [{"object": "FG-WDC1", "file": "site_FG.footprint.geojson"}],
            },
        }
        survey.update(survey_overrides)
        path = directory / "site.survey.json"
        path.write_text(json.dumps(survey))
        return str(path)

    def anchor(self):
        return self.mesh_actor.get_component_by_class.return_value

    def test_anchors_mesh_at_pivot_with_grid_convergence_and_creates_footprints(self):
        with tempfile.TemporaryDirectory() as directory:
            actors = self.helper.import_package(self.write_package(directory), ellipsoid_height_meters=230.5)
        self.assertEqual(actors, [self.mesh_actor, self.polygon_actor])
        self.mesh_actor.get_component_by_class.assert_any_call(self.anchor_class)
        anchor = self.anchor()
        anchor.set_editor_property.assert_any_call("georeference", self.georeference)
        location = anchor.move_to_longitude_latitude_height.call_args.args[0]
        self.assertEqual((location.x, location.y, location.z), (-91.18329928490297, 38.82478672628238, 230.5))
        anchor.set_east_south_up_rotation.assert_called_once_with(("quat", -0.4284007486780979))
        spline = self.polygon_actor.get_component_by_class.return_value
        points = spline.set_spline_points.call_args.args[0]
        self.assertTrue(all(point.z == 230.5 for point in points))
        self.assertEqual(self.import_task.destination_path, "/Game/LandXML")

    def test_recorded_height_is_used_and_convergence_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            self.helper.import_package(
                self.write_package(directory, height=12.0), apply_grid_convergence=False, import_footprints=False,
            )
        self.assertEqual(self.anchor().move_to_longitude_latitude_height.call_args.args[0].z, 12.0)
        self.anchor().set_east_south_up_rotation.assert_called_once_with(("quat", 0.0))
        self.editor.spawn_actor_from_class.assert_not_called()

    def test_invalid_packages_fail_before_importing_anything(self):
        cases = [
            ({}, {}),  # unknown ellipsoid height is never replaced by survey elevation
            ({"fbx": False}, {"ellipsoid_height_meters": 1.0}),
            ({"package": None}, {"ellipsoid_height_meters": 1.0}),
            ({"format": "other"}, {"ellipsoid_height_meters": 1.0}),
            ({"projection": {}}, {"ellipsoid_height_meters": 1.0}),
            ({}, {"ellipsoid_height_meters": float("nan")}),
        ]
        for package_options, call_options in cases:
            with self.subTest(package=package_options, call=call_options), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    self.helper.import_package(self.write_package(directory, **package_options), **call_options)
        self.unreal.AssetToolsHelpers.get_asset_tools.assert_not_called()

    def test_missing_georeference_fails_before_import(self):
        self.editor.get_selected_level_actors.return_value = []
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            self.helper.import_package(self.write_package(directory), ellipsoid_height_meters=1.0)
        self.unreal.AssetToolsHelpers.get_asset_tools.assert_not_called()

    def test_failure_after_placement_removes_created_actors(self):
        self.anchor().move_to_longitude_latitude_height.side_effect = RuntimeError("cesium")
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(RuntimeError):
            self.helper.import_package(self.write_package(directory), ellipsoid_height_meters=1.0)
        self.editor.destroy_actor.assert_called_once_with(self.mesh_actor)


if __name__ == "__main__":
    unittest.main()
