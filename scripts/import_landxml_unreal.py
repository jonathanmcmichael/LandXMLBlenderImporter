"""Run in Unreal Editor Python, then call import_package(path_to_survey_json, ...).

Imports a "LandXML Unreal Package" exported from Blender and places it with
Cesium for Unreal. Requires Cesium for Unreal and the Python Editor Script
Plugin. Select the intended CesiumGeoreference, or pass it explicitly. Nothing
is saved automatically.
"""

import json
import math
from pathlib import Path
import sys

import unreal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_cesium_polygons import create_polygon_actors, load_footprint, resolve_georeference  # noqa: E402


def load_package(survey_path):
    """Validate a package's survey JSON and the files it lists before touching the project."""
    survey_path = Path(survey_path)
    survey = json.loads(survey_path.read_text(encoding="utf-8"))
    if survey.get("format") != "landxml-survey-reference-v1":
        raise ValueError("Expected a LandXML survey reference (.survey.json)")
    package = survey.get("package")
    if not package:
        raise ValueError("This survey reference has no package block; export a LandXML Unreal Package")
    anchor = survey.get("cesium_anchor")
    if not anchor:
        raise ValueError("Survey reference has no Cesium anchor; export with a horizontal CRS")
    longitude, latitude = anchor["longitude_degrees"], anchor["latitude_degrees"]
    if not (
        all(math.isfinite(value) for value in (longitude, latitude))
        and -180 <= longitude <= 180 and -90 <= latitude <= 90
    ):
        raise ValueError("Cesium anchor must be finite longitude/latitude degrees")
    convergence = survey.get("projection", {}).get("meridian_convergence_degrees")
    if convergence is None or not math.isfinite(convergence):
        raise ValueError("Survey reference has no meridian convergence")
    fbx = survey_path.with_name(package["fbx"])
    if not fbx.is_file():
        raise ValueError(f"Missing package FBX: {fbx}")
    footprints = [load_footprint(survey_path.with_name(item["file"])) for item in package.get("footprints", ())]
    return survey, fbx, footprints


def resolve_height(survey, ellipsoid_height_meters):
    """The pivot's WGS84 ellipsoid height; survey elevation is never substituted."""
    recorded = survey["cesium_anchor"].get("ellipsoid_height_meters")
    if ellipsoid_height_meters is None:
        if recorded is None:
            raise ValueError(
                "Pivot ellipsoid height is unknown. Pass ellipsoid_height_meters= the pivot's WGS84 "
                "ellipsoid height (NOT its survey elevation; NAVD88 differs by the geoid separation)"
            )
        ellipsoid_height_meters = recorded
    if not math.isfinite(ellipsoid_height_meters):
        raise ValueError("Ellipsoid height must be finite meters")
    return float(ellipsoid_height_meters)


def import_meshes(fbx, destination):
    task = unreal.AssetImportTask()
    task.filename = str(fbx)
    task.destination_path = destination
    task.automated = True
    task.replace_existing = True
    task.save = False
    options = unreal.FbxImportUI()
    options.import_mesh = True
    options.import_as_skeletal = False
    options.import_animations = False
    options.mesh_type_to_import = unreal.FBXImportType.FBXIT_STATIC_MESH
    data = options.static_mesh_import_data
    data.combine_meshes = False
    # Convex hulls are useless for terrain; collision uses the triangles instead.
    data.auto_generate_collision = False
    data.import_uniform_scale = 1.0
    data.import_translation = unreal.Vector(0, 0, 0)
    data.import_rotation = unreal.Rotator(0, 0, 0)
    task.options = options
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    meshes = [
        asset for asset in map(unreal.load_asset, task.get_editor_property("imported_object_paths"))
        if isinstance(asset, unreal.StaticMesh)
    ]
    for mesh in meshes:
        body_setup = mesh.get_editor_property("body_setup")
        if body_setup is not None:
            body_setup.set_editor_property(
                "collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE,
            )
    return meshes


def add_component(actor, component_class):
    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    root = subsystem.k2_gather_subobject_data_for_instance(actor)[0]
    handle, reason = subsystem.add_new_subobject(
        unreal.AddNewSubobjectParams(parent_handle=root, new_class=component_class),
    )
    component = actor.get_component_by_class(component_class)
    if component is None:
        raise RuntimeError(f"Could not add {component_class.__name__} to {actor.get_actor_label()}: {reason}")
    return component


def import_package(
    survey_path,
    *,
    georeference=None,
    ellipsoid_height_meters=None,
    destination="/Game/LandXML",
    apply_grid_convergence=True,
    import_footprints=True,
):
    """Import the package FBX and anchor every surface at the survey pivot.

    The mesh's local zero is the survey pivot, so each actor is globe-anchored at
    the pivot's longitude/latitude/ellipsoid height. Local mesh axes are grid
    east/north; apply_grid_convergence yaws them by the meridian convergence so
    grid north points where it does on the globe. Footprint polygons are created
    at the same height; add them to one CesiumPolygonRasterOverlay afterward.
    """
    survey, fbx, footprints = load_package(survey_path)
    height = resolve_height(survey, ellipsoid_height_meters)
    editor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    georeference = resolve_georeference(editor, georeference)
    anchor_data = survey["cesium_anchor"]
    location = unreal.Vector(anchor_data["longitude_degrees"], anchor_data["latitude_degrees"], height)
    convergence = survey["projection"]["meridian_convergence_degrees"]
    # Cesium's east-south-up frame is left-handed, so positive yaw turns east toward
    # south: clockwise from above, matching the convergence azimuth of grid north.
    yaw = convergence if apply_grid_convergence else 0.0
    rotation = unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw).quaternion()

    meshes = import_meshes(fbx, destination)
    expected = len(survey["package"]["mesh_objects"])
    if len(meshes) != expected:
        raise RuntimeError(f"FBX import produced {len(meshes)} static mesh(es); expected {expected}")

    actors = []
    with unreal.ScopedEditorTransaction("Import LandXML Unreal package"):
        try:
            for mesh in meshes:
                actor = editor.spawn_actor_from_object(mesh, unreal.Vector(0, 0, 0))
                if actor is None:
                    raise RuntimeError(f"Could not place {mesh.get_name()}")
                actors.append(actor)
                actor.set_actor_label(mesh.get_name())
                anchor = add_component(actor, unreal.CesiumGlobeAnchorComponent)
                anchor.set_editor_property("georeference", georeference)
                anchor.move_to_longitude_latitude_height(location)
                anchor.set_east_south_up_rotation(rotation)
            if import_footprints:
                for data, rings in footprints:
                    actors.extend(create_polygon_actors(editor, georeference, data, rings, height))
        except Exception:
            for actor in reversed(actors):
                editor.destroy_actor(actor)
            raise
    editor.set_selected_level_actors(actors)
    polygon_count = len(actors) - len(meshes)
    unreal.log_warning(
        f"Placed {len(meshes)} LandXML surface(s) at lon {location.x:.9f}, lat {location.y:.9f}, "
        f"ellipsoid height {height:.3f} m, grid convergence yaw {yaw:.6f} deg"
        + (
            f"; created {polygon_count} footprint polygon actor(s). Add ALL polygons to the tileset's "
            "CesiumPolygonRasterOverlay, then refresh the tileset"
            if polygon_count else ""
        )
        + ". Verify against survey control, then save the level."
    )
    return actors
