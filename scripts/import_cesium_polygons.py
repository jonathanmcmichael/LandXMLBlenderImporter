"""Run in Unreal Editor Python, then call import_footprint(path, height_meters=...).

Requires Cesium for Unreal and Python Editor Script Plugin. Select the intended
CesiumGeoreference, or pass it explicitly. Nothing is saved automatically.
"""

import json
import math
from pathlib import Path

import unreal


def import_footprint(filepath, *, georeference=None, height_meters=0.0):
    """Create hole-free polygon actors; assign all to one overlay afterward.

    Height only places the polygon spline, not the imported terrain mesh.
    """
    if not math.isfinite(height_meters):
        raise ValueError("Polygon display height must be finite (ellipsoid meters)")
    data = json.loads(Path(filepath).read_text(encoding="utf-8"))
    if data.get("landxml", {}).get("format") != "landxml-cesium-footprint-v1":
        raise ValueError("Expected a LandXML Cesium footprint export")
    pieces = data.get("cesium_unreal", {}).get("pieces")
    if not pieces:
        raise ValueError("Footprint contains no Cesium polygon pieces")
    rings = []
    for piece in pieces:
        ring = piece["ring"]
        if len(ring) < 4 or ring[0] != ring[-1]:
            raise ValueError("Each polygon piece must be a closed ring with at least three vertices")
        for coordinate in ring:
            if (
                len(coordinate) != 2 or not all(math.isfinite(value) for value in coordinate)
                or not -180 <= coordinate[0] <= 180 or not -90 <= coordinate[1] <= 90
            ):
                raise ValueError("Polygon coordinates must be finite longitude/latitude pairs")
        rings.append(ring[:-1])
    editor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if georeference is None:
        selected = [
            actor for actor in editor.get_selected_level_actors()
            if isinstance(actor, unreal.CesiumGeoreference)
        ]
        if len(selected) != 1:
            raise ValueError("Select exactly one CesiumGeoreference actor, or pass georeference explicitly")
        georeference = selected[0]
    if not isinstance(georeference, unreal.CesiumGeoreference):
        raise ValueError("georeference must be a CesiumGeoreference actor")
    actors = []
    with unreal.ScopedEditorTransaction("Import LandXML Cesium footprint"):
        try:
            for index, ring in enumerate(rings):
                actor = editor.spawn_actor_from_class(unreal.CesiumCartographicPolygon, unreal.Vector())
                if actor is None:
                    raise RuntimeError(f"Could not create polygon actor {index + 1}")
                actors.append(actor)
                actor.set_actor_label(f"{data['landxml']['surface']}_Clip_{index + 1:04d}")
                anchor = actor.get_component_by_class(unreal.CesiumGlobeAnchorComponent)
                anchor.set_editor_property("georeference", georeference)
                center = unreal.Vector(
                    sum(point[0] for point in ring) / len(ring),
                    sum(point[1] for point in ring) / len(ring),
                    height_meters,
                )
                anchor.move_to_longitude_latitude_height(center)
                points = [
                    georeference.transform_longitude_latitude_height_position_to_unreal(
                        unreal.Vector(longitude, latitude, height_meters),
                    )
                    for longitude, latitude in ring
                ]
                spline = actor.get_component_by_class(unreal.SplineComponent)
                spline.set_spline_points(points, unreal.SplineCoordinateSpace.WORLD, False)
                for point_index in range(len(points)):
                    spline.set_spline_point_type(point_index, unreal.SplinePointType.LINEAR, False)
                spline.set_closed_loop(True, True)
        except Exception:
            for actor in reversed(actors):
                editor.destroy_actor(actor)
            raise
    editor.set_selected_level_actors(actors)
    unreal.log_warning(
        f"Created {len(actors)} polygon actors. Add ALL to the tileset's CesiumPolygonRasterOverlay "
        "Polygons array, then refresh the tileset. Holes are preserved by gaps between pieces. "
        "Clipping is visual and does not remove collision. Save the level when ready."
    )
    return actors
