"""Blender-independent LandXML TIN parsing and coordinate conversion."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET


UNIT_TO_METERS = {
    "MILLIMETERS": 0.001,
    "CENTIMETERS": 0.01,
    "METERS": 1.0,
    "KILOMETERS": 1000.0,
    "INCHES": 0.0254,
    "INTERNATIONAL_FEET": 0.3048,
    "US_SURVEY_FEET": 1200.0 / 3937.0,
    "MILES": 1609.344,
    "US_SURVEY_MILES": 5280.0 * 1200.0 / 3937.0,
}

POINT_ORDERS = ("NEZ", "ENZ")
"""NEZ = Northing, Easting, Elevation (LandXML 1.2 standard). ENZ = the
occasional non-standard Civil 3D export where Easting comes first."""

SCHEMA_GEOMETRY_ADAPTERS = {
    "Surface": "mesh",
    "Boundary": "curve and TIN clipping",
    "Breakline": "curve",
    "PlanFeature": "curve",
    "CoordGeom": "curve",
    "Line": "curve segment",
    "Curve": "sampled curve segment",
    "IrregularLine": "3D point-list curve",
    "Pipe": "centerline curve",
    "Struct": "network-node point",
    "CgPoint": "point-cloud vertex",
    "Location": "point-cloud vertex",
    "ProfAlign": "profile curve",
    "PVI": "profile vertex",
    "CrossSectSurf": "local cross-section curve",
}


class LandXMLError(ValueError):
    """Raised when a file has no usable authoritative TIN data."""


@dataclass(frozen=True)
class TinSurface:
    name: str
    points: dict[str, tuple[float, float, float]]
    faces: tuple[tuple[str, str, str], ...]
    skipped_face_count: int = 0
    skipped_face_reasons: tuple[tuple[str, int], ...] = ()
    boundaries: tuple[LandXMLCurve, ...] = ()


@dataclass(frozen=True)
class LandXMLCurve:
    name: str
    category: str
    points: tuple[tuple[float, float, float], ...]
    closed: bool
    attributes: tuple[tuple[str, str], ...] = ()
    properties: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LandXMLPoint:
    category: str
    coordinate: tuple[float, float, float]
    attributes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CurveData:
    name: str
    category: str
    points: tuple[tuple[float, float, float], ...]
    closed: bool
    attributes: tuple[tuple[str, str], ...]
    properties: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PointData:
    category: str
    coordinates: tuple[tuple[float, float, float], ...]
    attributes: tuple[tuple[tuple[str, str], ...], ...]


@dataclass(frozen=True)
class LandXMLNode:
    name: str
    namespace: str
    attributes: tuple[tuple[str, str], ...]
    text: str
    tail: str
    children: tuple[LandXMLNode, ...]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "attributes": dict(self.attributes),
            "text": self.text,
            "tail": self.tail,
            "children": [child.to_dict() for child in self.children],
        }

    def iter_json_chunks(self):
        encoder = json.JSONEncoder(ensure_ascii=True, separators=(",", ":"))
        yield '{"name":'
        yield encoder.encode(self.name)
        yield ',"namespace":'
        yield encoder.encode(self.namespace)
        yield ',"attributes":'
        yield encoder.encode(dict(self.attributes))
        yield ',"text":'
        yield encoder.encode(self.text)
        yield ',"tail":'
        yield encoder.encode(self.tail)
        yield ',"children":['
        for index, child in enumerate(self.children):
            if index:
                yield ","
            yield from child.iter_json_chunks()
        yield "]}"

    def iter_records(self):
        next_id = 0
        pending = [(self, None, 0)]
        while pending:
            node, parent_id, sibling_index = pending.pop()
            node_id = next_id
            next_id += 1
            yield {
                "id": node_id,
                "parent": parent_id,
                "index": sibling_index,
                "name": node.name,
                "namespace": node.namespace,
                "attributes": dict(node.attributes),
                "text": node.text,
                "tail": node.tail,
            }
            pending.extend(
                (child, node_id, index)
                for index, child in reversed(tuple(enumerate(node.children)))
            )


@dataclass(frozen=True)
class LandXMLDocument:
    root: LandXMLNode
    surfaces: tuple[TinSurface, ...]
    curves: tuple[LandXMLCurve, ...]
    points: tuple[LandXMLPoint, ...]
    declared_linear_unit: str | None
    source_units: str
    unit_warning: str | None


@dataclass(frozen=True)
class MeshData:
    name: str
    vertices: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[int, int, int], ...]
    skipped_face_count: int
    skipped_face_reasons: tuple[tuple[str, int], ...]
    degenerate_face_count: int
    source_face_count: int
    boundary_clipped_face_count: int


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _node_from_element(element: ET.Element) -> LandXMLNode:
    text = element.text or ""
    tail = element.tail or ""
    return LandXMLNode(
        name=_local_name(element.tag),
        namespace=_namespace(element.tag),
        attributes=tuple(element.attrib.items()),
        text=text if text.strip() else "",
        tail=tail if tail.strip() else "",
        children=tuple(_node_from_element(child) for child in element),
    )


def _parse_xyz(text: str | None, point_order: str, *, label: str) -> tuple[tuple[float, float, float], ...]:
    values = text.split() if text else []
    if len(values) % 3:
        raise LandXMLError(f"{label} must contain Northing/Easting/Elevation triples")
    coordinates = []
    for index in range(0, len(values), 3):
        try:
            first, second, elevation = map(float, values[index:index + 3])
        except ValueError as exc:
            raise LandXMLError(f"{label} contains a non-numeric coordinate") from exc
        if not all(math.isfinite(value) for value in (first, second, elevation)):
            raise LandXMLError(f"{label} contains a non-finite coordinate")
        easting, northing = (second, first) if point_order == "NEZ" else (first, second)
        coordinates.append((easting, northing, elevation))
    return tuple(coordinates)


def _element_xyz(element: ET.Element | None, point_order: str, *, label: str) -> tuple[float, float, float]:
    if element is None:
        raise LandXMLError(f"{label} is missing")
    coordinates = _parse_xyz(element.text, point_order, label=label)
    if len(coordinates) != 1:
        raise LandXMLError(f"{label} must contain exactly one coordinate triple")
    return coordinates[0]


def _cgpoint_xyz(element: ET.Element, point_order: str, *, label: str) -> tuple[float, float, float]:
    values = element.text.split() if element.text else []
    if len(values) not in {2, 3}:
        raise LandXMLError(f"{label} must contain Northing/Easting and optional elevation")
    try:
        first, second = map(float, values[:2])
        elevation = float(values[2]) if len(values) == 3 else 0.0
    except ValueError as exc:
        raise LandXMLError(f"{label} contains a non-numeric coordinate") from exc
    if not all(math.isfinite(value) for value in (first, second, elevation)):
        raise LandXMLError(f"{label} contains a non-finite coordinate")
    easting, northing = (second, first) if point_order == "NEZ" else (first, second)
    return easting, northing, elevation


def _sample_arc(element: ET.Element, point_order: str, *, label: str) -> tuple[tuple[float, float, float], ...]:
    start = _element_xyz(next(_descendants(element, "Start"), None), point_order, label=f"{label} Start")
    end = _element_xyz(next(_descendants(element, "End"), None), point_order, label=f"{label} End")
    center_element = next(_descendants(element, "Center"), None)
    if center_element is None or not center_element.text:
        raise LandXMLError(f"{label} circular curve requires Start, Center, and End")
    center_values = center_element.text.split()
    if len(center_values) < 2:
        raise LandXMLError(f"{label} Center must contain two coordinates")
    try:
        first, second = map(float, center_values[:2])
    except ValueError as exc:
        raise LandXMLError(f"{label} Center contains a non-numeric coordinate") from exc
    center_x, center_y = (second, first) if point_order == "NEZ" else (first, second)
    start_angle = math.atan2(start[1] - center_y, start[0] - center_x)
    end_angle = math.atan2(end[1] - center_y, end[0] - center_x)
    if element.get("rot", "ccw").lower() == "cw":
        angle_delta = -((start_angle - end_angle) % (2.0 * math.pi))
    else:
        angle_delta = (end_angle - start_angle) % (2.0 * math.pi)
    if math.isclose(angle_delta, 0.0, abs_tol=1e-12):
        angle_delta = -2.0 * math.pi if element.get("rot", "ccw").lower() == "cw" else 2.0 * math.pi
    radius = math.hypot(start[0] - center_x, start[1] - center_y)
    segments = max(2, math.ceil(abs(angle_delta) / math.radians(5.0)))
    return tuple(
        (
            center_x + radius * math.cos(start_angle + angle_delta * step / segments),
            center_y + radius * math.sin(start_angle + angle_delta * step / segments),
            start[2] + (end[2] - start[2]) * step / segments,
        )
        for step in range(segments + 1)
    )


def _parse_coordgeom(element: ET.Element, point_order: str, *, label: str) -> tuple[tuple[float, float, float], ...]:
    points: list[tuple[float, float, float]] = []
    for geometry in element:
        kind = _local_name(geometry.tag)
        if kind == "Line":
            start = _element_xyz(next(_descendants(geometry, "Start"), None), point_order, label=f"{label} Line Start")
            end = _element_xyz(next(_descendants(geometry, "End"), None), point_order, label=f"{label} Line End")
            segment = (start, end)
        elif kind == "IrregularLine":
            point_list = next(_descendants(geometry, "PntList3D"), None)
            segment = (
                _parse_xyz(point_list.text, point_order, label=f"{label} IrregularLine")
                if point_list is not None
                else ()
            )
        elif kind == "Curve":
            segment = _sample_arc(geometry, point_order, label=f"{label} Curve")
        else:
            continue
        if points and segment and points[-1] == segment[0]:
            points.extend(segment[1:])
        else:
            points.extend(segment)
    return tuple(points)


def _owning_surface(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> ET.Element | None:
    owner = parents.get(element)
    while owner is not None and _local_name(owner.tag) != "Surface":
        owner = parents.get(owner)
    return owner


def _parse_source_curves(
    root: ET.Element, point_order: str
) -> tuple[tuple[LandXMLCurve, ...], dict[ET.Element | None, list[LandXMLCurve]]]:
    """Return all curves plus boundary curves keyed by their enclosing Surface element (or None)."""
    curves: list[LandXMLCurve] = []
    boundaries_by_surface: dict[ET.Element | None, list[LandXMLCurve]] = {}
    parents = {child: parent for parent in root.iter() for child in parent}
    point_references = {}
    for point in _descendants(root, "CgPoint"):
        point_name = point.get("name") or point.get("id")
        if point_name:
            point_references[point_name] = _cgpoint_xyz(point, point_order, label=f"CgPoint '{point_name}'")
    for boundary in _descendants(root, "Boundary"):
        point_list = next(_descendants(boundary, "PntList3D"), None)
        if point_list is None:
            continue
        points = _parse_xyz(point_list.text, point_order, label="Boundary PntList3D")
        if len(points) < 3:
            raise LandXMLError("Boundary PntList3D must contain at least three points")
        if points[0] != points[-1]:
            points = (*points, points[0])
        boundary_curve = LandXMLCurve(
            name=boundary.get("name") or f"Boundary_{len(curves) + 1}",
            category="Boundary",
            points=points,
            closed=True,
            attributes=tuple(boundary.attrib.items()),
        )
        curves.append(boundary_curve)
        boundaries_by_surface.setdefault(_owning_surface(boundary, parents), []).append(boundary_curve)
    for breakline in _descendants(root, "Breakline"):
        point_list = next(_descendants(breakline, "PntList3D"), None)
        if point_list is None:
            continue
        points = _parse_xyz(point_list.text, point_order, label="Breakline PntList3D")
        if len(points) < 2:
            continue
        curves.append(
            LandXMLCurve(
                name=breakline.get("name") or f"Breakline_{len(curves) + 1}",
                category="Breakline",
                points=points,
                closed=False,
                attributes=tuple(breakline.attrib.items()),
            )
        )
    for coord_geom in _descendants(root, "CoordGeom"):
        owner = parents.get(coord_geom)
        if owner is None:
            continue
        category = _local_name(owner.tag)
        name = owner.get("name") or f"{category}_{len(curves) + 1}"
        points = _parse_coordgeom(coord_geom, point_order, label=name)
        if len(points) < 2:
            continue
        feature_element = next(_descendants(owner, "Feature"), None)
        properties = tuple(
            (prop.get("label", ""), prop.get("value", ""))
            for prop in _descendants(feature_element, "Property")
        ) if feature_element is not None else ()
        attributes = tuple(owner.attrib.items()) + (
            tuple((f"feature_{key}", value) for key, value in feature_element.attrib.items())
            if feature_element is not None else ()
        )
        curves.append(
            LandXMLCurve(
                name=name,
                category=category,
                points=points,
                closed=points[0] == points[-1],
                attributes=attributes,
                properties=properties,
            )
        )
    structures = {}
    for structure in _descendants(root, "Struct"):
        structure_name = structure.get("name")
        center = next((child for child in structure if _local_name(child.tag) == "Center"), None)
        if not structure_name or center is None:
            continue
        try:
            coordinate = _cgpoint_xyz(center, point_order, label=f"Struct '{structure_name}' Center")
        except LandXMLError:
            continue
        if coordinate is not None:
            structures[structure_name] = (structure, coordinate)

    for pipe in _descendants(root, "Pipe"):
        if next(_descendants(pipe, "CoordGeom"), None) is not None:
            continue
        endpoints = []
        pipe_name = pipe.get("name") or ""
        start_ref = pipe.get("refStart")
        end_ref = pipe.get("refEnd")
        if start_ref in structures and end_ref in structures:
            for structure_ref in (start_ref, end_ref):
                structure, center = structures[structure_ref]
                invert = next(
                    (
                        child for child in structure
                        if _local_name(child.tag) == "Invert"
                        and (child.get("refPipe") == pipe_name or not child.get("refPipe"))
                    ),
                    None,
                )
                elevation = center[2]
                if invert is not None and invert.get("elev") is not None:
                    try:
                        elevation = float(invert.get("elev"))
                    except ValueError:
                        pass
                endpoints.append((center[0], center[1], elevation))
        else:
            for tag in ("Start", "End"):
                endpoint = next((child for child in pipe if _local_name(child.tag) == tag), None)
                if endpoint is None:
                    endpoints = []
                    break
                point_reference = endpoint.get("pntRef") or endpoint.get("ref")
                if point_reference in point_references:
                    endpoints.append(point_references[point_reference])
                    continue
                try:
                    endpoints.append(_element_xyz(endpoint, point_order, label=f"Pipe {tag}"))
                except LandXMLError:
                    endpoints = []
                    break
        if len(endpoints) == 2:
            curves.append(
                LandXMLCurve(
                    name=pipe.get("name") or f"Pipe_{len(curves) + 1}",
                    category="Pipe",
                    points=tuple(endpoints),
                    closed=False,
                    attributes=tuple(pipe.attrib.items()),
                )
            )
    for cross_section_surface in _descendants(root, "CrossSectSurf"):
        cross_section = parents.get(cross_section_surface)
        if cross_section is None or cross_section.get("sta") is None:
            continue
        try:
            station = float(cross_section.get("sta"))
        except ValueError:
            continue
        for point_list in _descendants(cross_section_surface, "PntList2D"):
            values = point_list.text.split() if point_list.text else []
            if len(values) < 4 or len(values) % 2:
                continue
            try:
                pairs = tuple(
                    (float(values[index]), float(values[index + 1]))
                    for index in range(0, len(values), 2)
                )
            except ValueError:
                continue
            if not all(math.isfinite(value) for pair in pairs for value in pair):
                continue
            name = cross_section_surface.get("name") or f"CrossSect_{station:g}"
            curves.append(
                LandXMLCurve(
                    name=name,
                    category="CrossSectSurf",
                    points=tuple((offset, station, elevation) for offset, elevation in pairs),
                    closed=False,
                    attributes=tuple(cross_section_surface.attrib.items()) + (("station", str(station)),),
                )
            )
    for profile in _descendants(root, "ProfAlign"):
        pvis = tuple(_descendants(profile, "PVI"))
        profile_points = []
        for pvi in pvis:
            values = pvi.text.split() if pvi.text else []
            if len(values) < 2:
                continue
            try:
                station, elevation = map(float, values[:2])
            except ValueError:
                continue
            if math.isfinite(station) and math.isfinite(elevation):
                profile_points.append((station, 0.0, elevation))
        if len(profile_points) >= 2:
            curves.append(
                LandXMLCurve(
                    name=profile.get("name") or f"Profile_{len(curves) + 1}",
                    category="Profile",
                    points=tuple(profile_points),
                    closed=False,
                    attributes=tuple(profile.attrib.items()),
                )
            )
    return tuple(curves), boundaries_by_surface


def _parse_source_points(root: ET.Element, point_order: str) -> tuple[LandXMLPoint, ...]:
    points = []
    for category in ("CgPoint", "Location"):
        for point in _descendants(root, category):
            points.append(
                LandXMLPoint(
                    category=category,
                    coordinate=_cgpoint_xyz(point, point_order, label=category),
                    attributes=tuple(point.attrib.items()),
                )
            )
    for structure in _descendants(root, "Struct"):
        center = next((child for child in structure if _local_name(child.tag) == "Center"), None)
        if center is None:
            continue
        points.append(
            LandXMLPoint(
                category="Struct",
                coordinate=_cgpoint_xyz(center, point_order, label="Struct Center"),
                attributes=tuple(structure.attrib.items()) + tuple(
                    (f"{_local_name(child.tag)}_{key}", value)
                    for child in structure
                    for key, value in child.attrib.items()
                ),
            )
        )
    return tuple(points)


def _descendants(element: ET.Element, name: str) -> Iterable[ET.Element]:
    return (child for child in element.iter() if _local_name(child.tag) == name)


def _parse_surface(element: ET.Element, fallback_name: str, point_order: str) -> TinSurface | None:
    definition = next(_descendants(element, "Definition"), None)
    search_root = definition if definition is not None else element

    points: dict[str, tuple[float, float, float]] = {}
    for point in _descendants(search_root, "P"):
        point_id = point.get("id")
        values = point.text.split() if point.text else []
        if not point_id or len(values) < 3:
            continue
        try:
            first, second, elevation = map(float, values[:3])
        except ValueError:
            continue
        if not all(math.isfinite(value) for value in (first, second, elevation)):
            continue
        easting, northing = (second, first) if point_order == "NEZ" else (first, second)
        if point_id in points:
            raise LandXMLError(f"Surface '{element.get('name', fallback_name)}' has duplicate point ID '{point_id}'")
        points[point_id] = (easting, northing, elevation)

    faces: list[tuple[str, str, str]] = []
    skipped_reasons: dict[str, int] = {}
    for face in _descendants(search_root, "F"):
        ids = face.text.split() if face.text else []
        if len(ids) != 3:
            skipped_reasons["non_triangular"] = skipped_reasons.get("non_triangular", 0) + 1
            continue
        if any(point_id not in points for point_id in ids):
            skipped_reasons["missing_point"] = skipped_reasons.get("missing_point", 0) + 1
            continue
        faces.append((ids[0], ids[1], ids[2]))

    if not points or not faces:
        return None

    return TinSurface(
        name=element.get("name") or fallback_name,
        points=points,
        faces=tuple(faces),
        skipped_face_count=sum(skipped_reasons.values()),
        skipped_face_reasons=tuple(sorted(skipped_reasons.items())),
    )


def resolve_source_units(declared_unit: str | None, override: str = "AUTO") -> tuple[str, str | None]:
    if override != "AUTO":
        if override not in UNIT_TO_METERS:
            raise LandXMLError(f"Unsupported source units: {override}")
        return override, None

    normalized = "".join(character for character in (declared_unit or "").lower() if character.isalnum())
    unit_aliases = {
        "millimeter": "MILLIMETERS",
        "millimeters": "MILLIMETERS",
        "millimetre": "MILLIMETERS",
        "millimetres": "MILLIMETERS",
        "mm": "MILLIMETERS",
        "centimeter": "CENTIMETERS",
        "centimeters": "CENTIMETERS",
        "centimetre": "CENTIMETERS",
        "centimetres": "CENTIMETERS",
        "cm": "CENTIMETERS",
        "meter": "METERS",
        "meters": "METERS",
        "metre": "METERS",
        "metres": "METERS",
        "m": "METERS",
        "kilometer": "KILOMETERS",
        "kilometers": "KILOMETERS",
        "kilometre": "KILOMETERS",
        "kilometres": "KILOMETERS",
        "km": "KILOMETERS",
        "inch": "INCHES",
        "inches": "INCHES",
        "in": "INCHES",
        "ussurveyfoot": "US_SURVEY_FEET",
        "ussurveyfeet": "US_SURVEY_FEET",
        "surveyfoot": "US_SURVEY_FEET",
        "surveyfeet": "US_SURVEY_FEET",
        "internationalfoot": "INTERNATIONAL_FEET",
        "internationalfeet": "INTERNATIONAL_FEET",
        "foot": "US_SURVEY_FEET",
        "feet": "US_SURVEY_FEET",
        "ft": "US_SURVEY_FEET",
        "mile": "MILES",
        "miles": "MILES",
        "mi": "MILES",
        "ussurveymile": "US_SURVEY_MILES",
        "ussurveymiles": "US_SURVEY_MILES",
    }
    if normalized in unit_aliases:
        unit = unit_aliases[normalized]
        if normalized in {"foot", "feet", "ft"}:
            return unit, "LandXML declares generic feet; using US survey feet. Override if the source uses international feet."
        return unit, None
    if not normalized:
        return "US_SURVEY_FEET", "LandXML does not declare linear units; using US survey feet. Override if needed."
    raise LandXMLError(f"Unsupported LandXML linear unit: {declared_unit}")


def parse_landxml_document(
    path: str | Path,
    *,
    point_order: str = "NEZ",
    source_units: str = "AUTO",
) -> LandXMLDocument:
    """Read the document tree and the supported TIN surface geometry."""
    if point_order not in POINT_ORDERS:
        raise LandXMLError(f"Unsupported point order: {point_order}")

    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise LandXMLError(f"Could not read LandXML: {exc}") from exc

    surfaces = []
    surface_elements = []
    for index, element in enumerate(_descendants(root, "Surface"), start=1):
        parsed = _parse_surface(element, f"LandXML_Surface_{index}", point_order)
        if parsed is not None:
            surfaces.append(parsed)
            surface_elements.append(element)

    imperial = next(_descendants(root, "Imperial"), None)
    metric = next(_descendants(root, "Metric"), None)
    units = imperial if imperial is not None else metric
    declared_linear_unit = units.get("linearUnit") if units is not None else None
    effective_units, unit_warning = resolve_source_units(declared_linear_unit, source_units)
    curves, boundaries_by_surface = _parse_source_curves(root, point_order)
    points = _parse_source_points(root, point_order)
    unowned_boundaries = boundaries_by_surface.get(None, [])
    if unowned_boundaries and len(surfaces) > 1:
        raise LandXMLError("Document-level boundaries cannot be associated with multiple TIN surfaces")
    for index, element in enumerate(surface_elements):
        boundaries = boundaries_by_surface.get(element, []) + unowned_boundaries
        if boundaries:
            surfaces[index] = replace(surfaces[index], boundaries=tuple(boundaries))
    return LandXMLDocument(
        root=_node_from_element(root),
        surfaces=tuple(surfaces),
        curves=curves,
        points=points,
        declared_linear_unit=declared_linear_unit,
        source_units=effective_units,
        unit_warning=unit_warning,
    )


def parse_landxml(path: str | Path, *, point_order: str = "NEZ") -> tuple[TinSurface, ...]:
    """Read importable surfaces while preserving point IDs and source faces."""
    document = parse_landxml_document(path, point_order=point_order)
    if not document.surfaces:
        raise LandXMLError("LandXML contained no surfaces with valid Points and Faces")
    return document.surfaces


def shared_origin(surfaces: Iterable[TinSurface]) -> tuple[float, float, float]:
    """Return a single horizontal source-coordinate origin for aligned surfaces."""
    coordinates = [point for surface in surfaces for point in surface.points.values()]
    if not coordinates:
        raise LandXMLError("Cannot calculate an origin without points")
    return (
        min(point[0] for point in coordinates),
        min(point[1] for point in coordinates),
        0.0,
    )


def shared_document_origin(document: LandXMLDocument) -> tuple[float, float, float]:
    if document.surfaces:
        return shared_origin(document.surfaces)
    coordinates = [point for curve in document.curves for point in curve.points]
    coordinates.extend(point.coordinate for point in document.points)
    if not coordinates:
        return (0.0, 0.0, 0.0)
    return min(point[0] for point in coordinates), min(point[1] for point in coordinates), 0.0


def build_curve_data(
    curve: LandXMLCurve,
    *,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    source_units: str = "METERS",
) -> CurveData:
    try:
        scale = UNIT_TO_METERS[source_units]
    except KeyError as exc:
        raise LandXMLError(f"Unsupported source units: {source_units}") from exc
    return CurveData(
        name=curve.name,
        category=curve.category,
        points=tuple(
            (
                easting * scale if curve.category in {"Profile", "CrossSectSurf"} else (easting - origin[0]) * scale,
                northing * scale if curve.category in {"Profile", "CrossSectSurf"} else (northing - origin[1]) * scale,
                elevation * scale if curve.category in {"Profile", "CrossSectSurf"} else (elevation - origin[2]) * scale,
            )
            for easting, northing, elevation in curve.points
        ),
        closed=curve.closed,
        attributes=curve.attributes,
        properties=curve.properties,
    )


def build_point_data(
    points: Iterable[LandXMLPoint],
    *,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    source_units: str = "METERS",
) -> PointData:
    try:
        scale = UNIT_TO_METERS[source_units]
    except KeyError as exc:
        raise LandXMLError(f"Unsupported source units: {source_units}") from exc
    records = tuple(points)
    return PointData(
        category=records[0].category if records else "Point",
        coordinates=tuple(
            (
                (point.coordinate[0] - origin[0]) * scale,
                (point.coordinate[1] - origin[1]) * scale,
                (point.coordinate[2] - origin[2]) * scale,
            )
            for point in records
        ),
        attributes=tuple(point.attributes for point in records),
    )


def build_mesh_data(
    surface: TinSurface,
    *,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    source_units: str = "METERS",
) -> MeshData:
    """Map E/N/Z to Blender X/Y/Z and convert source units to meters."""
    try:
        scale = UNIT_TO_METERS[source_units]
    except KeyError as exc:
        raise LandXMLError(f"Unsupported source units: {source_units}") from exc

    vertices = []
    id_to_index = {}
    for point_id, (easting, northing, elevation) in surface.points.items():
        id_to_index[point_id] = len(vertices)
        vertices.append(
            (
                (easting - origin[0]) * scale,
                (northing - origin[1]) * scale,
                (elevation - origin[2]) * scale,
            )
        )

    source_faces = tuple(tuple(id_to_index[point_id] for point_id in face) for face in surface.faces)
    boundary_clipped_face_count = 0
    if surface.boundaries:
        vertices, faces, boundary_clipped_face_count = _clip_faces_to_boundaries(
            surface,
            vertices,
            source_faces,
            origin=origin,
            scale=scale,
        )
    else:
        faces = source_faces
    degenerate_face_count = sum(
        _is_degenerate_face(vertices, face_indices) for face_indices in faces
    )
    return MeshData(
        name=surface.name,
        vertices=tuple(vertices),
        faces=faces,
        skipped_face_count=surface.skipped_face_count,
        skipped_face_reasons=surface.skipped_face_reasons,
        degenerate_face_count=degenerate_face_count,
        source_face_count=len(source_faces),
        boundary_clipped_face_count=boundary_clipped_face_count,
    )


def _clip_faces_to_boundaries(
    surface: TinSurface,
    source_vertices: list[tuple[float, float, float]],
    source_faces: tuple[tuple[int, int, int], ...],
    *,
    origin: tuple[float, float, float],
    scale: float,
) -> tuple[list[tuple[float, float, float]], tuple[tuple[int, int, int], ...], int]:
    try:
        from shapely import constrained_delaunay_triangles
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
    except ImportError as exc:
        raise LandXMLError("Shapely is required to clip a LandXML TIN boundary") from exc

    outer_rings = []
    hide_rings = []
    active_boundaries = [
        boundary
        for boundary in surface.boundaries
        if dict(boundary.attributes).get("edgeTrim", "true").lower() == "true"
    ]
    if not active_boundaries:
        return source_vertices, source_faces, 0

    for boundary in active_boundaries:
        attributes = dict(boundary.attributes)
        ring = [
            ((easting - origin[0]) * scale, (northing - origin[1]) * scale)
            for easting, northing, _ in boundary.points
        ]
        boundary_type = attributes.get("bndType", "outer").lower()
        if boundary_type == "outer":
            outer_rings.append(ring)
        elif boundary_type == "hide":
            hide_rings.append(ring)
        else:
            raise LandXMLError(f"Unsupported edge-trim boundary type '{boundary_type}'")

    if not outer_rings:
        raise LandXMLError("An edge-trim boundary requires at least one outer boundary loop")

    outer_polygons = [Polygon(ring) for ring in outer_rings]
    if any(not polygon.is_valid or polygon.area <= 0.0 for polygon in outer_polygons):
        raise LandXMLError("LandXML outer boundary contains an invalid or zero-area loop")
    holes_by_outer: list[list[list[tuple[float, float]]]] = [[] for _ in outer_polygons]
    for ring in hide_rings:
        hole = Polygon(ring)
        if not hole.is_valid or hole.area <= 0.0:
            raise LandXMLError("LandXML hide boundary contains an invalid or zero-area loop")
        owner = next((i for i, polygon in enumerate(outer_polygons) if polygon.contains(hole)), None)
        if owner is None:
            raise LandXMLError("LandXML hide boundary is not contained by an outer boundary")
        holes_by_outer[owner].append(ring)
    trimmed_polygons = [
        Polygon(outer_rings[index], holes=holes_by_outer[index])
        for index in range(len(outer_rings))
    ]
    if any(not polygon.is_valid for polygon in trimmed_polygons):
        raise LandXMLError("LandXML boundary loops overlap or self-intersect")
    clip_shape = unary_union(trimmed_polygons)

    result_vertices: list[tuple[float, float, float]] = []
    result_faces: list[tuple[int, int, int]] = []
    vertex_indices: dict[tuple, int] = {}
    index_to_id = tuple(surface.points)

    def add_vertex(point: tuple[float, float, float], source_id: str | None = None) -> int:
        key = ("id", source_id) if source_id is not None else ("coord", *(round(value, 12) for value in point))
        index = vertex_indices.get(key)
        if index is None:
            index = len(result_vertices)
            vertex_indices[key] = index
            result_vertices.append(point)
        return index

    changed_source_faces = 0
    for source_face in source_faces:
        point_ids = tuple(index_to_id[index] for index in source_face)
        triangle_points = tuple(source_vertices[index] for index in source_face)
        triangle = Polygon(tuple(point[:2] for point in triangle_points))
        if triangle.is_empty or triangle.area <= 1e-24:
            continue
        if clip_shape.covers(triangle):
            result_faces.append(tuple(add_vertex(point, point_id) for point, point_id in zip(triangle_points, point_ids)))
            continue

        changed_source_faces += 1
        clipped = clip_shape.intersection(triangle)
        if clipped.is_empty:
            continue
        polygons = [clipped] if clipped.geom_type == "Polygon" else [shape for shape in getattr(clipped, "geoms", ()) if shape.geom_type == "Polygon"]
        source_area = _signed_area_xy(triangle_points)
        for polygon in polygons:
            if polygon.area <= 1e-24:
                continue
            triangles = constrained_delaunay_triangles(polygon)
            for output_triangle in triangles.geoms:
                coordinates = tuple(output_triangle.exterior.coords)[:3]
                output_points = tuple(
                    (x, y, _interpolate_triangle_z((x, y), triangle_points))
                    for x, y in coordinates
                )
                if _signed_area_xy(output_points) * source_area < 0.0:
                    output_points = (output_points[0], output_points[2], output_points[1])
                output_ids = []
                for output_point in output_points:
                    source_id = next(
                        (
                            point_ids[index]
                            for index, source_point in enumerate(triangle_points)
                            if math.isclose(output_point[0], source_point[0], abs_tol=1e-10)
                            and math.isclose(output_point[1], source_point[1], abs_tol=1e-10)
                        ),
                        None,
                    )
                    output_ids.append(add_vertex(output_point, source_id))
                if len(set(output_ids)) == 3:
                    result_faces.append(tuple(output_ids))

    return result_vertices, tuple(result_faces), changed_source_faces


def _signed_area_xy(points: tuple[tuple[float, float, float], ...]) -> float:
    return sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    ) / 2.0


def _interpolate_triangle_z(
    point: tuple[float, float], triangle: tuple[tuple[float, float, float], ...]
) -> float:
    (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = triangle
    denominator = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if math.isclose(denominator, 0.0, abs_tol=1e-24):
        return (z1 + z2 + z3) / 3.0
    first_weight = ((y2 - y3) * (point[0] - x3) + (x3 - x2) * (point[1] - y3)) / denominator
    second_weight = ((y3 - y1) * (point[0] - x3) + (x1 - x3) * (point[1] - y3)) / denominator
    third_weight = 1.0 - first_weight - second_weight
    return first_weight * z1 + second_weight * z2 + third_weight * z3


def _is_degenerate_face(
    vertices: list[tuple[float, float, float]], face: tuple[int, int, int]
) -> bool:
    """Return whether a source triangle has repeated vertices or zero area."""
    if len(set(face)) != 3:
        return True

    first, second, third = (vertices[index] for index in face)
    edge_one = tuple(second[index] - first[index] for index in range(3))
    edge_two = tuple(third[index] - first[index] for index in range(3))
    cross = (
        edge_one[1] * edge_two[2] - edge_one[2] * edge_two[1],
        edge_one[2] * edge_two[0] - edge_one[0] * edge_two[2],
        edge_one[0] * edge_two[1] - edge_one[1] * edge_two[0],
    )
    return math.isclose(sum(component * component for component in cross), 0.0, abs_tol=1e-24)


def geometry_fingerprint(
    vertices: Iterable[tuple[float, float, float]], faces: Iterable[tuple[int, ...]]
) -> str:
    """Return a stable SHA-256 fingerprint of ordered mesh geometry."""
    payload = {
        "faces": [list(face) for face in faces],
        "vertices": [list(vertex) for vertex in vertices],
    }
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def match_breakline_mesh_edges(
    vertices: Iterable[tuple[float, float, float]],
    edges: Iterable[tuple[int, int]],
    segments: Iterable[tuple[tuple[float, float, float], tuple[float, float, float]]],
    *,
    tolerance: float = 1e-4,
) -> tuple[tuple[int, ...], int, int]:
    """Return matching mesh-edge indices and matched/total breakline segment counts."""
    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise LandXMLError("Breakline match tolerance must be a positive finite distance")

    coordinates = tuple(vertices)

    def coordinate_key(point: tuple[float, float, float]) -> tuple[int, int, int]:
        return tuple(round(value / tolerance) for value in point)

    edge_indices = {}
    for edge_index, (first, second) in enumerate(edges):
        key = tuple(sorted((coordinate_key(coordinates[first]), coordinate_key(coordinates[second]))))
        edge_indices[key] = edge_index

    matching_edges = set()
    matched_segments = total_segments = 0
    for first, second in segments:
        total_segments += 1
        key = tuple(sorted((coordinate_key(first), coordinate_key(second))))
        edge_index = edge_indices.get(key)
        if edge_index is not None:
            matching_edges.add(edge_index)
            matched_segments += 1
    return tuple(sorted(matching_edges)), matched_segments, total_segments

