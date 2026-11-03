import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch


class UnrealPolygonHelperTests(unittest.TestCase):
    def setUp(self):
        self.editor = MagicMock()
        self.actors = [MagicMock(), MagicMock()]
        self.editor.spawn_actor_from_class.side_effect = self.actors

        class Georeference:
            def transform_longitude_latitude_height_position_to_unreal(self, vector):
                return vector

        self.georeference = Georeference()
        self.editor.get_selected_level_actors.return_value = [self.georeference]
        self.unreal = types.SimpleNamespace(
            EditorActorSubsystem=object,
            CesiumGeoreference=Georeference,
            CesiumCartographicPolygon=type("Polygon", (), {}),
            CesiumGlobeAnchorComponent=type("Anchor", (), {}),
            SplineComponent=type("Spline", (), {}),
            Vector=lambda x=0, y=0, z=0: (x, y, z),
            SplineCoordinateSpace=types.SimpleNamespace(WORLD="world"),
            SplinePointType=types.SimpleNamespace(LINEAR="linear"),
            get_editor_subsystem=lambda cls: self.editor,
            ScopedEditorTransaction=MagicMock(),
            log_warning=MagicMock(),
        )
        path = Path(__file__).resolve().parents[1] / "scripts" / "import_cesium_polygons.py"
        spec = importlib.util.spec_from_file_location("_unreal_polygon_helper", path)
        self.helper = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"unreal": self.unreal}):
            spec.loader.exec_module(self.helper)

    def export(self, **overrides):
        data = {
            "landxml": {"format": "landxml-cesium-footprint-v1", "surface": "Test"},
            "cesium_unreal": {
                "pieces": [
                    {"ring": [[-91, 38], [-90.9, 38], [-91, 38.1], [-91, 38]]},
                    {"ring": [[-90.9, 38], [-90.9, 38.1], [-91, 38.1], [-90.9, 38]]},
                ],
            },
        }
        data.update(overrides)
        return data

    def run_import(self, data=None, **options):
        with tempfile.TemporaryDirectory() as directory:
            filepath = Path(directory) / "footprint.geojson"
            filepath.write_text(json.dumps(self.export() if data is None else data))
            return self.helper.import_footprint(str(filepath), **options)

    def test_creates_all_pieces_as_closed_linear_world_splines(self):
        actors = self.run_import(height_meters=250)
        self.assertEqual(actors, self.actors)
        for actor in actors:
            component = actor.get_component_by_class.return_value
            component.set_editor_property.assert_called_once_with("georeference", self.georeference)
            points, space, update = component.set_spline_points.call_args.args
            self.assertEqual(len(points), 3)
            self.assertEqual(space, "world")
            self.assertFalse(update)
            self.assertTrue(all(point[2] == 250 for point in points))
            self.assertEqual(component.set_spline_point_type.call_count, 3)
            component.set_closed_loop.assert_called_once_with(True, True)
        self.editor.set_selected_level_actors.assert_called_once_with(actors)

    def test_missing_georeference_and_bad_input_do_not_spawn_actors(self):
        self.editor.get_selected_level_actors.return_value = []
        with self.assertRaises(ValueError):
            self.run_import()
        with self.assertRaises(ValueError):
            self.run_import({"landxml": {"format": "wrong"}})
        invalid = self.export()
        invalid["cesium_unreal"]["pieces"][0]["ring"][0][0] = 1000
        with self.assertRaises(ValueError):
            self.run_import(invalid)
        self.editor.spawn_actor_from_class.assert_not_called()

    def test_partial_failure_removes_created_actors(self):
        self.editor.spawn_actor_from_class.side_effect = [self.actors[0], None]
        with self.assertRaises(RuntimeError):
            self.run_import(georeference=self.georeference)
        self.editor.destroy_actor.assert_called_once_with(self.actors[0])


if __name__ == "__main__":
    unittest.main()
