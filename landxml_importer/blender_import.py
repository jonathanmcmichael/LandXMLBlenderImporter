"""Blender mesh creation for parsed LandXML surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

import bpy
from mathutils import Matrix

from .georef import GeoreferenceError, ImageBounds, planar_uvs, resolve_bounds
from .footprint import surface_footprint
from .survey import survey_reference
from .landxml import (
    UNIT_TO_METERS,
    build_curve_data,
    build_mesh_data,
    build_point_data,
    cogo_pivot,
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
    horizontal_epsg: str = "",
    vertical_datum: str = "",
    ellipsoid_height: str = "",
    pivot_point_name: str = "",
):
    document = parse_landxml_document(
        filepath,
        point_order=point_order,
        source_units=source_units,
    )
    surfaces = document.surfaces
    source_units = document.source_units
    selected_point = None
    if pivot_point_name:
        if custom_origin is not None:
            raise ValueError("Choose either a LandXML COGO pivot or a manual survey pivot, not both")
        selected_point = cogo_pivot(document.points, pivot_point_name)
    origin = selected_point.coordinate if selected_point is not None else custom_origin
    origin = origin if origin is not None else (
        shared_document_origin(document) if shift_to_origin else (0.0, 0.0, 0.0)
    )
    reference = survey_reference(
        origin,
        source_units=source_units,
        unit_to_meters=UNIT_TO_METERS[source_units],
        horizontal_epsg=horizontal_epsg,
        vertical_datum=vertical_datum,
        ellipsoid_height=ellipsoid_height,
    )
    if selected_point is not None:
        reference["pivot_point"] = dict(selected_point.attributes)
    reference_json = json.dumps(reference, ensure_ascii=True, allow_nan=False)
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
        collection["landxml_survey_reference"] = reference_json

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

            skipped_reasons = ", ".join(
                f"{reason}: {count}" for reason, count in data.skipped_face_reasons
            ) or "none"
            print(
                f"LandXML surface '{data.name}': {len(data.vertices)} vertices, "
                f"{len(data.faces)} faces, {data.skipped_face_count} skipped "
                f"({skipped_reasons})."
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
            obj["landxml_invisible_face_count"] = data.invisible_face_count
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
        for obj in imported_objects:
            if obj.get("landxml_category") in {"Profile", "CrossSectSurf"}:
                continue
            obj["landxml_survey_reference"] = reference_json
            obj["landxml_import_collection"] = collection.name
            obj.lock_location = (True, True, True)
            obj.lock_rotation = (True, True, True)
            obj.lock_scale = (True, True, True)
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


def _write_json(filepath: str | Path, document: dict) -> None:
    Path(filepath).write_text(
        json.dumps(document, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8",
    )


def export_survey_reference(obj: bpy.types.Object, filepath: str) -> None:
    """Export a reference only while the imported local coordinate frame is intact."""
    _write_json(filepath, survey_reference_document(obj))


def survey_reference_document(obj: bpy.types.Object) -> dict:
    collection_name = obj.get("landxml_import_collection")
    collection = bpy.data.collections.get(collection_name) if collection_name else None
    if collection is None or "landxml_survey_reference" not in obj:
        raise ValueError("Re-import this object to create a portable survey reference")
    reference_json = obj["landxml_survey_reference"]
    objects = [
        item for item in collection.all_objects
        if item.get("landxml_survey_reference") == reference_json
    ]
    bpy.context.view_layer.update()
    identity = Matrix.Identity(4)
    for item in objects:
        if item.matrix_world != identity:
            raise ValueError(f"Object '{item.name}' has transformed placement; restore imported transforms before export")
    reference = json.loads(reference_json)
    reference["objects"] = [item.name for item in objects]
    reference["source_sha256"] = collection["landxml_source_sha256"]
    return reference


def export_cesium_footprint(
    obj: bpy.types.Object, filepath: str, *, horizontal_epsg: str = "",
    edge_offset_meters: float = 0.0, simplify_meters: float = 0.0,
) -> dict:
    result = cesium_footprint_document(
        obj, horizontal_epsg=horizontal_epsg,
        edge_offset_meters=edge_offset_meters, simplify_meters=simplify_meters,
    )
    _write_json(filepath, result)
    return result


def cesium_footprint_document(
    obj: bpy.types.Object, *, horizontal_epsg: str = "",
    edge_offset_meters: float = 0.0, simplify_meters: float = 0.0,
) -> dict:
    if obj.type != "MESH" or obj.get("landxml_category") != "Surface":
        raise ValueError("Select an imported LandXML TIN surface")
    bpy.context.view_layer.update()
    if obj.matrix_world != Matrix.Identity(4):
        raise ValueError("Restore imported object transforms before exporting its geographic footprint")
    if obj.modifiers:
        raise ValueError("Remove modifiers before exporting; footprint uses the raw imported TIN")
    if object_geometry_fingerprint(obj) != obj.get("landxml_geometry_fingerprint"):
        raise ValueError("Surface geometry has changed; re-import before exporting its geographic footprint")
    reference = json.loads(obj.get("landxml_survey_reference", "{}"))
    crs = reference.get("horizontal_crs")
    epsg = horizontal_epsg.strip() or (crs["id"] if crs else "")
    result = surface_footprint(
        (tuple(vertex.co) for vertex in obj.data.vertices),
        (tuple(polygon.vertices) for polygon in obj.data.polygons),
        origin=(
            obj["landxml_origin_easting"],
            obj["landxml_origin_northing"],
            obj["landxml_origin_elevation"],
        ),
        unit_to_meters=obj["landxml_unit_to_meters"],
        horizontal_epsg=epsg,
        name=obj.name,
        edge_offset_meters=edge_offset_meters,
        simplify_meters=simplify_meters,
    )
    result["landxml"]["source_sha256"] = obj.get("landxml_source_sha256", "")
    return result


def _file_token(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._") or "surface"


def export_unreal_package(
    obj: bpy.types.Object,
    filepath: str,
    *,
    selected_only: bool = False,
    include_footprints: bool = True,
    horizontal_epsg: str = "",
    edge_offset_meters: float = 0.0,
    simplify_meters: float = 0.0,
) -> dict:
    """Write FBX, survey reference and per-surface footprints for one LandXML import.

    Every check and document is computed before anything is written so a failure
    never leaves a partial package that disagrees with itself.
    """
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch to Object Mode before exporting")
    if bpy.context.scene.unit_settings.scale_length != 1.0:
        raise ValueError("Set Scene Units > Unit Scale to 1.0 so 1 Blender unit exports as 1 meter")
    reference = survey_reference_document(obj)
    surfaces = [
        item for item in (bpy.data.objects[name] for name in reference["objects"])
        if item.type == "MESH" and item.get("landxml_category") == "Surface"
        and (not selected_only or item.select_get())
    ]
    if not surfaces:
        raise ValueError("No imported TIN surfaces to export" + (" in the selection" if selected_only else ""))
    hidden = [item.name for item in surfaces if not item.visible_get()]
    if hidden:
        raise ValueError(f"Unhide surfaces before exporting: {', '.join(hidden)}")

    fbx_path = Path(filepath).with_suffix(".fbx")
    stem = fbx_path.stem
    has_crs = bool(horizontal_epsg.strip() or reference.get("horizontal_crs"))
    footprints: list[tuple[Path, dict]] = []
    warnings: list[str] = []
    if include_footprints and has_crs:
        used: set[str] = set()
        for item in surfaces:
            token = _file_token(item.name)
            while token.lower() in used:
                token += "_"
            used.add(token.lower())
            footprints.append((
                fbx_path.with_name(f"{stem}_{token}.footprint.geojson"),
                cesium_footprint_document(
                    item, horizontal_epsg=horizontal_epsg,
                    edge_offset_meters=edge_offset_meters, simplify_meters=simplify_meters,
                ),
            ))
    elif include_footprints:
        warnings.append("No horizontal CRS; Cesium footprints were skipped")

    reference["package"] = {
        "fbx": fbx_path.name,
        "mesh_objects": [item.name for item in surfaces],
        "footprints": [
            {"object": item.name, "file": path.name}
            for item, (path, _) in zip(surfaces, footprints)
        ],
        "fbx_units": "meters (Unreal imports 1 m as 100 uu)",
    }

    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    previous_selection = [item for item in view_layer.objects if item.select_get()]
    try:
        for item in previous_selection:
            item.select_set(False)
        for item in surfaces:
            item.select_set(True)
        view_layer.objects.active = surfaces[0]
        status = bpy.ops.export_scene.fbx(
            filepath=str(fbx_path),
            use_selection=True,
            object_types={"MESH"},
            apply_unit_scale=True,
            apply_scale_options="FBX_SCALE_NONE",
            axis_forward="-Z",
            axis_up="Y",
            bake_space_transform=False,
            use_mesh_modifiers=True,
            mesh_smooth_type="FACE",
            add_leaf_bones=False,
            bake_anim=False,
            path_mode="COPY",
            embed_textures=True,
        )
    finally:
        for item in view_layer.objects:
            item.select_set(item in previous_selection)
        view_layer.objects.active = previous_active
    if status != {"FINISHED"}:
        raise ValueError("Blender FBX export failed")

    survey_path = fbx_path.with_name(f"{stem}.survey.json")
    _write_json(survey_path, reference)
    for path, document in footprints:
        _write_json(path, document)
    return {
        "fbx": str(fbx_path),
        "survey": str(survey_path),
        "footprints": [str(path) for path, _ in footprints],
        "surface_count": len(surfaces),
        "warnings": warnings,
    }


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
