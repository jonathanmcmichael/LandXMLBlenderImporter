"""Blender mesh creation for parsed LandXML surfaces."""

from __future__ import annotations

import math
from pathlib import Path

import bmesh
import bpy

from .landxml import UNIT_TO_METERS, build_mesh_data, parse_landxml, shared_origin

_SMOOTH_ANGLE = math.radians(30)


def _finalize_shading(obj: bpy.types.Object, mesh: bpy.types.Mesh) -> None:
    """Recalculate consistent face normals and smooth-shade by angle.

    LandXML's <F> triangles don't guarantee consistent winding, so raw
    normals can be flipped; this fixes that while keeping real slope
    breaks crisp and smoothing continuous terrain.
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    # recalc_face_normals only makes adjacent faces mutually consistent; on
    # an open sheet like a TIN (no enclosed volume) it has no notion of "up"
    # and can pick the downward-facing orientation for the whole surface.
    # Terrain is predominantly near-horizontal, so use the sign of the
    # summed Z component to detect and correct a whole-mesh flip.
    if sum(face.normal.z for face in bm.faces) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    with bpy.context.temp_override(
        active_object=obj, selected_editable_objects=[obj], selected_objects=[obj], object=obj
    ):
        bpy.ops.object.shade_smooth_by_angle(angle=_SMOOTH_ANGLE)


def import_landxml(
    filepath: str,
    *,
    source_units: str,
    shift_to_origin: bool,
    point_order: str = "NEZ",
):
    surfaces = parse_landxml(filepath, point_order=point_order)
    origin = shared_origin(surfaces) if shift_to_origin else (0.0, 0.0, 0.0)
    imported_objects = []

    collection = bpy.data.collections.new(f"LandXML_{Path(filepath).stem}")
    bpy.context.collection.children.link(collection)

    for surface in surfaces:
        data = build_mesh_data(surface, origin=origin, source_units=source_units)
        mesh = bpy.data.meshes.new(data.name)
        mesh.from_pydata(data.vertices, [], data.faces)
        mesh.update()

        obj = bpy.data.objects.new(data.name, mesh)
        collection.objects.link(obj)
        _finalize_shading(obj, mesh)
        obj["landxml_source"] = str(Path(filepath))
        obj["landxml_source_units"] = source_units
        obj["landxml_point_order"] = point_order
        obj["landxml_unit_to_meters"] = UNIT_TO_METERS[source_units]
        obj["landxml_origin_easting"] = origin[0]
        obj["landxml_origin_northing"] = origin[1]
        obj["landxml_origin_elevation"] = origin[2]
        obj["landxml_vertex_count"] = len(data.vertices)
        obj["landxml_face_count"] = len(data.faces)
        obj["landxml_skipped_face_count"] = data.skipped_face_count
        obj.select_set(True)
        imported_objects.append(obj)

    bpy.context.view_layer.objects.active = imported_objects[-1]
    return imported_objects

