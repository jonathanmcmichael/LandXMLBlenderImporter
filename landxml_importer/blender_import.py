"""Blender mesh creation for parsed LandXML surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import bpy

from .georef import GeoreferenceError, ImageBounds, planar_uvs, resolve_bounds
from .landxml import (
    UNIT_TO_METERS,
    build_curve_data,
    build_mesh_data,
    build_point_data,
    geometry_fingerprint,
    match_breakline_mesh_edges,
    parse_landxml_document,
    shared_document_origin,
)

ORTHO_UV_NAME = "Ortho"


@dataclass(frozen=True)
class LandXMLImportResult:
    surfaces: tuple[bpy.types.Object, ...]
    curves: tuple[bpy.types.Object, ...]
    point_clouds: tuple[bpy.types.Object, ...]
    metadata_text: bpy.types.Text
    source_units: str
    unit_warning: str | None

    @property
    def objects(self) -> tuple[bpy.types.Object, ...]:
        return self.surfaces + self.curves + self.point_clouds


def object_geometry_fingerprint(obj: bpy.types.Object) -> str:
    """Fingerprint raw mesh data, deliberately excluding modifiers and transforms."""
    mesh = obj.data
    vertices = tuple(tuple(vertex.co) for vertex in mesh.vertices)
    faces = tuple(tuple(polygon.vertices) for polygon in mesh.polygons)
    return geometry_fingerprint(vertices, faces)


def _remove_import(
    collection: bpy.types.Collection,
    objects: list[bpy.types.Object],
    metadata_texts: list[bpy.types.Text],
) -> None:
    """Remove a failed import so incomplete data cannot look authoritative."""
    for obj in objects:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
    for child in tuple(collection.children):
        collection.children.unlink(child)
        bpy.data.collections.remove(child)
    bpy.data.collections.remove(collection)
    for metadata_text in metadata_texts:
        bpy.data.texts.remove(metadata_text)


def _new_child_collection(parent: bpy.types.Collection, name: str) -> bpy.types.Collection:
    collection = bpy.data.collections.new(name)
    parent.children.link(collection)
    return collection


def _new_curve_object(collection: bpy.types.Collection, data, *, origin: tuple[float, float, float]):
    curve = bpy.data.curves.new(data.name, type="CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    points = list(data.points)
    if data.closed and len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if not points:
        bpy.data.curves.remove(curve)
        return None
    spline.points.add(len(points) - 1)
    for point, coordinate in zip(spline.points, points):
        point.co = (*coordinate, 1.0)
    spline.use_cyclic_u = data.closed
    obj = bpy.data.objects.new(data.name, curve)
    collection.objects.link(obj)
    obj["landxml_category"] = data.category
    obj["landxml_attributes"] = json.dumps(dict(data.attributes), ensure_ascii=True)
    obj["landxml_properties"] = json.dumps(dict(data.properties), ensure_ascii=True)
    obj["landxml_origin_easting"] = origin[0]
    obj["landxml_origin_northing"] = origin[1]
    obj["landxml_origin_elevation"] = origin[2]
    return obj


def apply_breaklines_to_surface(
    surface: bpy.types.Object,
    breakline_objects: list[bpy.types.Object],
    *,
    tolerance: float,
    mark_sharp: bool,
    mark_seams: bool,
    smooth_surface: bool,
) -> tuple[int, int, int]:
    if not mark_sharp and not mark_seams:
        raise ValueError("Choose Mark Sharp, Mark UV Seams, or both")
    segments = []
    for obj in breakline_objects:
        for spline in obj.data.splines:
            points = [tuple(point.co[:3]) for point in spline.points]
            segments.extend(zip(points, points[1:]))

    mesh = surface.data
    vertices = tuple(tuple(vertex.co) for vertex in mesh.vertices)
    edges = tuple(tuple(edge.vertices) for edge in mesh.edges)
    matched_edges, matched_segments, total_segments = match_breakline_mesh_edges(
        vertices,
        edges,
        segments,
        tolerance=tolerance,
    )
    for edge_index in matched_edges:
        edge = mesh.edges[edge_index]
        if mark_sharp:
            edge.use_edge_sharp = True
        if mark_seams:
            edge.use_seam = True
    if mark_sharp and smooth_surface:
        for polygon in mesh.polygons:
            polygon.use_smooth = True
    mesh.update()
    surface["landxml_breakline_segments_matched"] = matched_segments
    surface["landxml_breakline_segments_unmatched"] = total_segments - matched_segments
    surface["landxml_breakline_edges_marked_sharp"] = len(matched_edges) if mark_sharp else 0
    surface["landxml_breakline_edges_marked_seam"] = len(matched_edges) if mark_seams else 0
    return matched_segments, total_segments, len(matched_edges)


def _write_document_metadata(
    root,
    name: str,
    metadata_texts: list[bpy.types.Text],
) -> tuple[bpy.types.Text, int]:
    metadata_chunks = []
    buffered_lines = []
    buffered_chars = 0
    record_count = 0

    def flush_chunk():
        nonlocal buffered_chars
        if not buffered_lines:
            return
        text = bpy.data.texts.new(f"{name}_metadata_{len(metadata_chunks):04d}.jsonl")
        text.write("".join(buffered_lines))
        metadata_chunks.append(text.name)
        metadata_texts.append(text)
        buffered_lines.clear()
        buffered_chars = 0

    for record in root.iter_records():
        line = json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n"
        buffered_lines.append(line)
        buffered_chars += len(line)
        record_count += 1
        if buffered_chars >= 1_048_576:
            flush_chunk()
    flush_chunk()

    index = bpy.data.texts.new(f"{name}_metadata.json")
    index.write(
        json.dumps(
            {
                "format": "landxml-tree-jsonl-v1",
                "record_count": record_count,
                "chunks": metadata_chunks,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )
    metadata_texts.append(index)
    return index, record_count


def import_landxml(
    filepath: str,
    *,
    source_units: str = "AUTO",
    shift_to_origin: bool,
    point_order: str = "NEZ",
    custom_origin: tuple[float, float, float] | None = None,
    validate_original_faces: bool = True,
):
    document = parse_landxml_document(
        filepath,
        point_order=point_order,
        source_units=source_units,
    )
    surfaces = document.surfaces
    source_units = document.source_units
    origin = custom_origin if custom_origin is not None else (
        shared_document_origin(document) if shift_to_origin else (0.0, 0.0, 0.0)
    )
    source_path = Path(filepath)
    with source_path.open("rb") as source_file:
        source_sha256 = hashlib.file_digest(source_file, "sha256").hexdigest()
    surface_objects = []
    curve_objects = []
    point_objects = []
    imported_objects: list[bpy.types.Object] = []
    metadata_text = None
    metadata_texts: list[bpy.types.Text] = []

    collection = bpy.data.collections.new(f"LandXML_{Path(filepath).stem}")
    bpy.context.scene.collection.children.link(collection)
    surface_collection = _new_child_collection(collection, "Surfaces")
    curve_collections = {
        "Boundary": _new_child_collection(collection, "Boundaries"),
        "Breakline": _new_child_collection(collection, "Breaklines"),
        "PlanFeature": _new_child_collection(collection, "PlanFeatures"),
    }
    point_collection = _new_child_collection(collection, "Points")

    try:
        metadata_name = f"LandXML_{Path(filepath).stem}"
        metadata_text, metadata_record_count = _write_document_metadata(
            document.root,
            metadata_name,
            metadata_texts,
        )
        collection["landxml_metadata_text"] = metadata_text.name
        collection["landxml_metadata_chunks"] = json.dumps(
            [text.name for text in metadata_texts if text != metadata_text],
            ensure_ascii=True,
        )
        collection["landxml_metadata_record_count"] = metadata_record_count
        collection["landxml_declared_linear_unit"] = document.declared_linear_unit or ""
        collection["landxml_source_units"] = source_units
        collection["landxml_source_sha256"] = source_sha256
        collection["landxml_root_attributes"] = json.dumps(dict(document.root.attributes), ensure_ascii=True)

        for surface in surfaces:
            data = build_mesh_data(surface, origin=origin, source_units=source_units)
            mesh = bpy.data.meshes.new(data.name)
            mesh.from_pydata(data.vertices, [], data.faces)
            mesh.update()

            obj = bpy.data.objects.new(data.name, mesh)
            surface_collection.objects.link(obj)
            imported_objects.append(obj)
            surface_objects.append(obj)

            if validate_original_faces and (
                len(mesh.vertices) != len(data.vertices) or len(mesh.polygons) != len(data.faces)
            ):
                raise RuntimeError(
                    f"Surface '{data.name}' failed output-geometry validation: expected "
                    f"{len(data.vertices)} vertices and {len(data.faces)} faces, got "
                    f"{len(mesh.vertices)} vertices and {len(mesh.polygons)} faces."
                )

            obj["landxml_source"] = str(source_path)
            obj["landxml_category"] = "Surface"
            obj["landxml_import_collection"] = collection.name
            obj["landxml_source_sha256"] = source_sha256
            obj["landxml_source_units"] = source_units
            obj["landxml_declared_linear_unit"] = document.declared_linear_unit or ""
            obj["landxml_point_order"] = point_order
            obj["landxml_unit_to_meters"] = UNIT_TO_METERS[source_units]
            obj["landxml_origin_easting"] = origin[0]
            obj["landxml_origin_northing"] = origin[1]
            obj["landxml_origin_elevation"] = origin[2]
            obj["landxml_vertex_count"] = len(data.vertices)
            obj["landxml_face_count"] = len(data.faces)
            obj["landxml_source_face_count"] = data.source_face_count
            obj["landxml_boundary_clipped_face_count"] = data.boundary_clipped_face_count
            obj["landxml_skipped_face_count"] = data.skipped_face_count
            obj["landxml_skipped_face_reasons"] = json.dumps(dict(data.skipped_face_reasons))
            obj["landxml_degenerate_face_count"] = data.degenerate_face_count
            # Fingerprint Blender's stored (float32) mesh so the integrity check can match it later.
            obj["landxml_geometry_fingerprint"] = object_geometry_fingerprint(obj)
            obj["landxml_validation_passed"] = validate_original_faces
            obj["landxml_metadata_text"] = metadata_text.name
            obj.lock_location = (True, True, True)
            obj.lock_rotation = (True, True, True)
            obj.lock_scale = (True, True, True)
            obj.select_set(True)

        for curve in document.curves:
            curve_data = build_curve_data(curve, origin=origin, source_units=source_units)
            target_collection = curve_collections.get(curve_data.category)
            if target_collection is None:
                target_collection = _new_child_collection(collection, f"{curve_data.category}s")
                curve_collections[curve_data.category] = target_collection
            obj = _new_curve_object(target_collection, curve_data, origin=origin)
            if obj is not None:
                obj["landxml_source_units"] = source_units
                obj["landxml_unit_to_meters"] = UNIT_TO_METERS[source_units]
                obj["landxml_metadata_text"] = metadata_text.name
                obj["landxml_import_collection"] = collection.name
                imported_objects.append(obj)
                curve_objects.append(obj)
                obj.select_set(True)

        point_groups = {}
        for point in document.points:
            point_groups.setdefault(point.category, []).append(point)
        for category, source_points in point_groups.items():
            point_data = build_point_data(source_points, origin=origin, source_units=source_units)
            mesh = bpy.data.meshes.new("LandXML_CgPoints")
            mesh.from_pydata(point_data.coordinates, [], [])
            mesh.update()
            category_attribute = mesh.attributes.new("landxml_category", "STRING", "POINT")
            identifier_attribute = mesh.attributes.new("landxml_source_id", "STRING", "POINT")
            for point_index, attributes in enumerate(point_data.attributes):
                values = dict(attributes)
                category_attribute.data[point_index].value = category.encode("utf-8")
                identifier_attribute.data[point_index].value = (
                    values.get("name") or values.get("id") or values.get("desc") or str(point_index)
                ).encode("utf-8")
            obj = bpy.data.objects.new(f"LandXML_{category}", mesh)
            point_collection.objects.link(obj)
            obj["landxml_category"] = category
            obj["landxml_point_count"] = len(point_data.coordinates)
            obj["landxml_source_units"] = source_units
            obj["landxml_unit_to_meters"] = UNIT_TO_METERS[source_units]
            obj["landxml_point_order"] = point_order
            obj["landxml_source_sha256"] = source_sha256
            obj["landxml_origin_easting"] = origin[0]
            obj["landxml_origin_northing"] = origin[1]
            obj["landxml_origin_elevation"] = origin[2]
            obj["landxml_metadata_text"] = metadata_text.name
            imported_objects.append(obj)
            point_objects.append(obj)
            obj.select_set(True)
    except Exception:
        _remove_import(collection, imported_objects, metadata_texts)
        raise

    if surface_objects:
        bpy.context.view_layer.objects.active = surface_objects[-1]
    elif imported_objects:
        bpy.context.view_layer.objects.active = imported_objects[-1]
    return LandXMLImportResult(
        surfaces=tuple(surface_objects),
        curves=tuple(curve_objects),
        point_clouds=tuple(point_objects),
        metadata_text=metadata_text,
        source_units=source_units,
        unit_warning=document.unit_warning,
    )


def _ortho_material(image: bpy.types.Image) -> bpy.types.Material:
    name = f"LandXML_Ortho_{Path(image.filepath).stem}"
    material = bpy.data.materials.get(name)
    if material is not None:
        return material
    material = bpy.data.materials.new(name)
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.uv_map = ORTHO_UV_NAME
    uv_node.location = (-700, 300)
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.extension = "CLIP"
    texture.location = (-450, 300)
    links.new(uv_node.outputs["UV"], texture.inputs["Vector"])
    bsdf = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
    links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
    return material


def apply_orthophoto(
    objects: list[bpy.types.Object], image_path: str
) -> tuple[ImageBounds, int, int]:
    """Project a georeferenced image onto LandXML objects by source coordinates.

    Returns the image bounds, total vertices, and vertices outside the image.
    Raw vertices and faces are untouched, so integrity fingerprints still match.
    """
    image = bpy.data.images.load(image_path, check_existing=True)
    width, height = image.size
    if width == 0 or height == 0:
        raise GeoreferenceError(
            "Blender could not read this image; convert it to JPEG or PNG with a world file (gdal_translate -co WORLDFILE=YES)"
        )
    bounds = resolve_bounds(image_path, width, height)

    planned = []
    total = outside = 0
    for obj in objects:
        units = obj["landxml_source_units"]
        if bounds.linear_units and bounds.linear_units != units:
            raise GeoreferenceError(
                f"Image units are {bounds.linear_units} but '{obj.name}' was imported as {units}"
            )
        mesh = obj.data
        coords = [0.0] * (len(mesh.vertices) * 3)
        mesh.vertices.foreach_get("co", coords)
        uvs = planar_uvs(
            zip(coords[0::3], coords[1::3]),
            bounds,
            origin=(obj["landxml_origin_easting"], obj["landxml_origin_northing"]),
            unit_to_meters=obj["landxml_unit_to_meters"],
        )
        total += len(uvs)
        outside += sum(not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0) for u, v in uvs)
        planned.append((obj, uvs))

    if total and outside == total:
        raise GeoreferenceError(
            "No surface vertices fall inside the image; check that the image and LandXML share a CRS and units"
        )

    material = _ortho_material(image)
    for obj, uvs in planned:
        mesh = obj.data
        loop_vertices = [0] * len(mesh.loops)
        mesh.loops.foreach_get("vertex_index", loop_vertices)
        layer = mesh.uv_layers.get(ORTHO_UV_NAME) or mesh.uv_layers.new(name=ORTHO_UV_NAME)
        layer.data.foreach_set("uv", [c for index in loop_vertices for c in uvs[index]])
        if mesh.materials:
            mesh.materials[0] = material
        else:
            mesh.materials.append(material)
        obj["landxml_ortho_source"] = image_path
        obj["landxml_ortho_bounds"] = json.dumps(
            {"left": bounds.left, "top": bounds.top, "right": bounds.right, "bottom": bounds.bottom}
        )
        obj["landxml_ortho_georeference"] = bounds.source
    return bounds, total, outside

