"""Install a built extension ZIP into Blender and exercise it end to end.

Run in background Blender with an isolated profile so the user's
preferences are untouched:

    BLENDER_USER_RESOURCES=<temp dir> blender -b --factory-startup \
        --python-exit-code 1 --python scripts/blender_smoke_test.py -- <zip>

Checks that the bundled Shapely wheel loads, a boundary-trimmed TIN
imports and passes the integrity validator, and an orthophoto with a
world file can be applied.
"""

import importlib
import json
from pathlib import Path
import sys
import tempfile

import bpy

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_MODULE = "bl_ext.user_default.landxml_tin_importer"


def check(condition, message):
    if not condition:
        raise RuntimeError(f"Smoke test failed: {message}")
    print(f"PASS {message}")


def main():
    zip_path = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
    bpy.ops.extensions.package_install_files(
        filepath=str(zip_path), repo="user_default", enable_on_install=True
    )
    import addon_utils

    check(addon_utils.check(ADDON_MODULE)[1], f"{zip_path.name} installs and enables")

    import shapely

    check("extensions" in Path(shapely.__file__).parts, "Shapely loads from the bundled wheel")

    blender_import = importlib.import_module(f"{ADDON_MODULE}.blender_import")
    result = blender_import.import_landxml(
        str(REPO_ROOT / "tests" / "fixtures" / "trimmed_surface.xml"), shift_to_origin=False
    )
    surface = result.surfaces[0]
    check(surface["landxml_boundary_clipped_face_count"] > 0, "edge-trim boundary clips the TIN")

    bpy.context.view_layer.objects.active = surface
    check(
        bpy.ops.object.landxml_validate_integrity() == {"FINISHED"},
        "integrity validator accepts the unmodified mesh",
    )

    with tempfile.TemporaryDirectory() as directory:
        image_path = Path(directory) / "ortho.png"
        image = bpy.data.images.new("ortho", 40, 40)
        image.filepath_raw = str(image_path)
        image.file_format = "PNG"
        image.save()
        # 0.1 m pixels covering 0..4 m, origin at the upper-left pixel centre.
        image_path.with_suffix(".pgw").write_text("0.1\n0\n0\n-0.1\n0.05\n3.95\n")

        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        surface.select_set(True)
        status = bpy.ops.object.landxml_apply_orthophoto(filepath=str(image_path))
    check(status == {"FINISHED"} and surface.data.materials, "orthophoto material is applied")

    import pyproj

    check("extensions" in Path(pyproj.__file__).parts, "pyproj loads from the bundled wheel")
    with tempfile.TemporaryDirectory() as directory:
        pivot = (3000000.123456789, 1698067.4612223296, 5000.0)
        result = blender_import.import_landxml(
            str(REPO_ROOT / "tests" / "fixtures" / "survey_surface.xml"),
            shift_to_origin=True, custom_origin=pivot, horizontal_epsg="2232",
            vertical_datum="NAVD88", ellipsoid_height="1490.5",
        )
        survey_surface = result.surfaces[0]
        check(len(survey_surface.data.polygons) == 1
              and survey_surface["landxml_source_face_count"] == 2
              and survey_surface["landxml_invisible_face_count"] == 1,
              "invisible source triangle is recorded but not added to Blender mesh")
        check(tuple(survey_surface.data.vertices[0].co) == (0, 0, 0), "survey pivot is local mesh zero")
        check(abs(survey_surface.data.vertices[1].co.x - 10 * 1200 / 3937) < 1e-6,
              "US survey feet convert to local meters")
        bpy.context.view_layer.objects.active = survey_surface
        filepath = str(Path(directory) / "survey.json")
        check(bpy.ops.export_scene.landxml_survey_reference(filepath=filepath) == {"FINISHED"},
              "survey sidecar export operator succeeds")
        reference = json.loads(Path(filepath).read_text())
        check(reference["origin"]["easting"] == pivot[0], "sidecar preserves double-precision pivot")
        check(abs(reference["cesium_anchor"]["latitude_degrees"] - 39.75) < 1e-6,
              "State Plane pivot converts to Cesium latitude")
        check(reference["cesium_anchor"]["ellipsoid_height_meters"] == 1490.5,
              "explicit Cesium height remains separate from survey elevation")
        footprint_path = str(Path(directory) / "footprint.geojson")
        check(bpy.ops.export_scene.landxml_cesium_footprint(filepath=footprint_path) == {"FINISHED"},
              "Cesium footprint export operator succeeds")
        footprint = json.loads(Path(footprint_path).read_text())
        check(len(footprint["features"]) == 1 and footprint["cesium_unreal"]["piece_count"] == 1,
              "visible triangle exports one footprint and no hidden triangle")
        check(footprint["features"][0]["geometry"]["coordinates"][0][0][0] < -105,
              "footprint coordinates are geographic longitude, not local mesh coordinates")
        offset_path = str(Path(directory) / "offset.geojson")
        check(bpy.ops.export_scene.landxml_cesium_footprint(
            filepath=offset_path, edge_offset_meters=-0.5, simplify_meters=0.25,
        ) == {"FINISHED"}, "footprint export accepts edge offset and simplify")
        offset = json.loads(Path(offset_path).read_text())["landxml"]
        check(offset["edge_offset_meters"] == -0.5
              and offset["area_square_meters"] < footprint["landxml"]["area_square_meters"],
              "inward edge offset shrinks the Cesium cutout")
        package_dir = Path(directory) / "package"
        package_dir.mkdir()
        expected = sorted(tuple(round(c, 6) for c in v.co) for v in survey_surface.data.vertices)
        check(bpy.ops.export_scene.landxml_unreal_package(filepath=str(package_dir / "site.fbx"))
              == {"FINISHED"}, "Unreal package export operator succeeds")
        package_survey = json.loads((package_dir / "site.survey.json").read_text())
        footprint_name = package_survey["package"]["footprints"][0]["file"]
        check(package_survey["package"]["fbx"] == "site.fbx"
              and package_survey["origin"] == reference["origin"]
              and (package_dir / footprint_name).is_file(),
              "package writes FBX, survey JSON and footprint that reference each other")
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=str(package_dir / "site.fbx"))
        fbx_objects = [item for item in bpy.data.objects if item not in before]
        check(len(fbx_objects) == 1, "package FBX contains only the TIN surface")
        fbx_world = sorted(
            tuple(round(c, 6) for c in fbx_objects[0].matrix_world @ v.co) for v in fbx_objects[0].data.vertices
        )
        check(fbx_world == expected, "FBX round-trips meter-scale vertices with the survey pivot at zero")
        bpy.data.objects.remove(fbx_objects[0])
        bpy.context.view_layer.objects.active = survey_surface
        survey_surface.location.x = 1
        bpy.context.view_layer.update()
        rejected_dir = Path(directory) / "rejected"
        rejected_dir.mkdir()
        try:
            blender_import.export_unreal_package(survey_surface, str(rejected_dir / "site.fbx"))
        except ValueError:
            pass
        else:
            raise RuntimeError("Smoke test failed: transformed package export was accepted")
        check(not any(rejected_dir.iterdir()), "failed package export writes no partial files")
        survey_surface.location.x = 1
        try:
            blender_import.export_survey_reference(survey_surface, filepath)
        except ValueError:
            pass
        else:
            raise RuntimeError("Smoke test failed: transformed survey object was accepted")
        survey_surface.location.x = 0
        bpy.context.view_layer.update()
        name = survey_surface.name
        blend_path = str(Path(directory) / "survey.blend")
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        bpy.ops.wm.open_mainfile(filepath=blend_path)
        blender_import.export_survey_reference(bpy.data.objects[name], filepath)
        check(json.loads(Path(filepath).read_text())["origin"] == reference["origin"],
              "survey reference persists across saving and reopening Blender")

    status = bpy.ops.import_scene.landxml_tin(
        filepath=str(REPO_ROOT / "tests" / "fixtures" / "survey_surface.xml"),
        coordinate_system="NAD83 / Colorado Central (ftUS) - EPSG:2232",
        horizontal_epsg="4326",
        use_custom_pivot=True,
        use_cogo_pivot=True,
        pivot_point="1 - Building Corner",
        pivot_easting="3000000.123456789",
        pivot_northing="1698067.4612223296",
        pivot_elevation="5000",
    )
    check(status == {"FINISHED"}, "import operator accepts searchable NAD83 text selection")
    reference = json.loads(bpy.context.active_object["landxml_survey_reference"])
    check(reference["horizontal_crs"]["id"] == "EPSG:2232",
          "dropdown overrides stale manual EPSG and persists chosen CRS")
    check(reference["origin"] == {
        "easting": 3000000.123456789, "northing": 1698067.4612223296, "elevation": 5000.0,
    }, "COGO point sets exact shared XYZ origin, overriding manual and automatic pivots")
    check(reference["pivot_point"]["code"] == "Building Corner", "selected COGO identity persists")
    collection_name = bpy.context.active_object["landxml_import_collection"]
    points = [
        obj for obj in bpy.data.objects
        if obj.get("landxml_import_collection") == collection_name and obj.get("landxml_category") == "CgPoint"
    ]
    check(len(points) == 1 and tuple(points[0].data.vertices[0].co) == (0, 0, 0),
          "selected COGO point imports at local zero")

    with tempfile.TemporaryDirectory() as directory:
        diagnostic_path = Path(directory) / "diagnostics.xml"
        diagnostic_path.write_text(
            """<LandXML><Surfaces><Surface name="Diagnostics"><Definition>
            <Pnts><P id="1">0 0 0</P><P id="2">0 1 0</P>
            <P id="3">1 0 0</P><P id="4">1 1 0</P></Pnts>
            <Faces><F>1 2 3</F><F>1 2 3 4</F><F>1 2 999</F></Faces>
            </Definition></Surface></Surfaces></LandXML>""",
            encoding="utf-8",
        )
        status = bpy.ops.import_scene.landxml_tin(
            filepath=str(diagnostic_path), source_units="METERS",
        )
        check(status == {"FINISHED"}, "import operator accepts a surface with skipped faces")
        diagnostic_surface = bpy.context.active_object
        reasons = json.loads(diagnostic_surface["landxml_skipped_face_reasons"])
        check(reasons == {"missing_point": 1, "non_triangular": 1}
              and diagnostic_surface["landxml_skipped_face_count"] == 2,
              "operator retains per-surface skip counts and reasons")

        empty_path = Path(directory) / "no_surfaces.xml"
        empty_path.write_text("<LandXML><Surfaces><Surface name='Empty'/></Surfaces></LandXML>",
                              encoding="utf-8")
        status = bpy.ops.import_scene.landxml_tin(
            filepath=str(empty_path), source_units="METERS",
        )
        check(status == {"FINISHED"}, "import operator handles a document with no usable TIN surfaces")

main()
