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


main()
