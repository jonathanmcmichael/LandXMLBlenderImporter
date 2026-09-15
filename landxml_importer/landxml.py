"""Blender-independent LandXML TIN parsing and coordinate conversion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET


UNIT_TO_METERS = {
    "METERS": 1.0,
    "INTERNATIONAL_FEET": 0.3048,
    "US_SURVEY_FEET": 1200.0 / 3937.0,
}


class LandXMLError(ValueError):
    """Raised when a file has no usable authoritative TIN data."""


@dataclass(frozen=True)
class TinSurface:
    name: str
    points: dict[str, tuple[float, float, float]]
    faces: tuple[tuple[str, str, str], ...]
    skipped_face_count: int = 0


@dataclass(frozen=True)
class MeshData:
    name: str
    vertices: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[int, int, int], ...]
    skipped_face_count: int


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _descendants(element: ET.Element, name: str) -> Iterable[ET.Element]:
    return (child for child in element.iter() if _local_name(child.tag) == name)


def _parse_surface(element: ET.Element, fallback_name: str) -> TinSurface | None:
    definition = next(_descendants(element, "Definition"), None)
    search_root = definition if definition is not None else element

    points: dict[str, tuple[float, float, float]] = {}
    for point in _descendants(search_root, "P"):
        point_id = point.get("id")
        values = point.text.split() if point.text else []
        if not point_id or len(values) < 3:
            continue
        try:
            northing, easting, elevation = map(float, values[:3])
        except ValueError:
            continue
        if point_id in points:
            raise LandXMLError(f"Surface '{element.get('name', fallback_name)}' has duplicate point ID '{point_id}'")
        points[point_id] = (easting, northing, elevation)

    faces: list[tuple[str, str, str]] = []
    skipped = 0
    for face in _descendants(search_root, "F"):
        ids = face.text.split() if face.text else []
        if len(ids) < 3 or any(point_id not in points for point_id in ids[:3]):
            skipped += 1
            continue
        faces.append((ids[0], ids[1], ids[2]))

    if not points or not faces:
        return None

    return TinSurface(
        name=element.get("name") or fallback_name,
        points=points,
        faces=tuple(faces),
        skipped_face_count=skipped,
    )


def parse_landxml(path: str | Path) -> tuple[TinSurface, ...]:
    """Read importable surfaces while preserving point IDs and source faces."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise LandXMLError(f"Could not read LandXML: {exc}") from exc

    surfaces = []
    for index, element in enumerate(_descendants(root, "Surface"), start=1):
        parsed = _parse_surface(element, f"LandXML_Surface_{index}")
        if parsed is not None:
            surfaces.append(parsed)

    if not surfaces:
        raise LandXMLError("LandXML contained no surfaces with valid Points and Faces")
    return tuple(surfaces)


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

    faces = tuple(tuple(id_to_index[point_id] for point_id in face) for face in surface.faces)
    return MeshData(
        name=surface.name,
        vertices=tuple(vertices),
        faces=faces,
        skipped_face_count=surface.skipped_face_count,
    )

