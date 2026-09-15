"""Blender mesh creation for parsed LandXML surfaces."""

from __future__ import annotations

from pathlib import Path

import bpy

from .landxml import UNIT_TO_METERS, build_mesh_data, parse_landxml, shared_origin


def import_landxml(
    filepath: str,
    *,
    source_units: str,
    shift_to_origin: bool,
):
    surfaces = parse_landxml(filepath)
    origin = shared_origin(surfaces) if shift_to_origin else (0.0, 0.0, 0.0)
    imported_objects = []

    for surface in surfaces:
        data = build_mesh_data(surface, origin=origin, source_units=source_units)
        mesh = bpy.data.meshes.new(data.name)
        mesh.from_pydata(data.vertices, [], data.faces)
        mesh.update()

        obj = bpy.data.objects.new(data.name, mesh)
        bpy.context.collection.objects.link(obj)
        obj["landxml_source"] = str(Path(filepath))
        obj["landxml_source_units"] = source_units
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

