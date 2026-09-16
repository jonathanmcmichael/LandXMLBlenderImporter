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
    bm.normal_update()

    # A TIN is a heightfield: every (easting, northing) maps to exactly one
    # elevation, so there are no true overhangs and each triangle's correct
    # "up" winding can be decided from its own geometry alone. Don't use
    # neighbor-consistency algorithms like recalc_face_normals here -- a TIN
    # is an open sheet that can have separate triangulation islands meeting
    # only at a single shared vertex (common around long sliver triangles),
    # and consistency propagation can't cross that gap, leaving isolated
    # patches flipped even after correcting the mesh's overall orientation.
    to_flip = [face for face in bm.faces if face.normal.z < 0]
    if to_flip:
        bmesh.ops.reverse_faces(bm, faces=to_flip)

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

