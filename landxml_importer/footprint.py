"""Visible-TIN footprints with geographic rings and hole-free Unreal pieces."""

from __future__ import annotations

import math
from typing import Iterable

from shapely import constrained_delaunay_triangles, union_all
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from .survey import projected_wgs84_transform


def surface_footprint(
    vertices: Iterable[tuple[float, float, float]],
    faces: Iterable[tuple[int, ...]],
    *,
    origin: tuple[float, float, float],
    unit_to_meters: float,
    horizontal_epsg: str,
    name: str,
) -> dict:
    """Union raw visible faces in local meters; never use a hull or fill holes."""
    if not horizontal_epsg.strip():
        raise ValueError("Select the source projected CRS before exporting a Cesium footprint")
    if not math.isfinite(unit_to_meters) or unit_to_meters <= 0:
        raise ValueError("Source-unit scale must be finite and positive")
    if len(origin) != 3 or not all(math.isfinite(value) for value in origin):
        raise ValueError("Survey pivot must contain three finite coordinates")
    coordinates = tuple(vertices)
    if any(len(point) != 3 or not all(math.isfinite(value) for value in point) for point in coordinates):
        raise ValueError("Mesh vertices must contain finite XYZ coordinates")
    triangles = []
    zero_area = 0
    for face in faces:
        if len(face) != 3 or any(index < 0 or index >= len(coordinates) for index in face):
            raise ValueError("Footprint requires valid triangular mesh faces")
        triangle = Polygon([coordinates[index][:2] for index in face])
        if triangle.area == 0:
            zero_area += 1
            continue
        if not triangle.is_valid:
            raise ValueError("Mesh contains an invalid footprint triangle")
        triangles.append(triangle)
    if not triangles:
        raise ValueError("Surface has no visible nonzero-area triangles to export")
    footprint = union_all(triangles)
    if footprint.geom_type not in {"Polygon", "MultiPolygon"} or not footprint.is_valid:
        raise ValueError("Visible triangles did not produce a valid polygon footprint")
    polygons = [footprint] if footprint.geom_type == "Polygon" else list(footprint.geoms)
    crs, transformer, scale = projected_wgs84_transform(horizontal_epsg, unit_to_meters)

    def geographic_ring(ring):
        result = []
        for x, y in ring.coords:
            longitude, latitude = transformer.transform(
                (x / unit_to_meters + origin[0]) * scale,
                (y / unit_to_meters + origin[1]) * scale,
                errcheck=True,
            )
            if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                raise ValueError("Footprint contains invalid longitude/latitude")
            result.append([longitude, latitude])
        if any(abs(a[0] - b[0]) > 180 for a, b in zip(result, result[1:])):
            raise ValueError("Antimeridian-crossing footprints require splitting before export")
        return result

    features = []
    pieces = []
    for index, polygon in enumerate(polygons):
        polygon = orient(polygon, sign=1.0)
        geographic = [geographic_ring(polygon.exterior)]
        geographic.extend(geographic_ring(ring) for ring in polygon.interiors)
        features.append({
            "type": "Feature",
            "properties": {"surface": name, "island": index, "hole_count": len(polygon.interiors)},
            "geometry": {"type": "Polygon", "coordinates": geographic},
        })
        # A Cesium Cartographic Polygon has one ring, not an outer ring plus holes.
        parts = (
            list(constrained_delaunay_triangles(polygon).geoms)
            if polygon.interiors else [polygon]
        )
        if not union_all(parts).equals(polygon):
            raise ValueError("Hole-free Cesium pieces do not exactly cover the surface footprint")
        for part in parts:
            pieces.append({
                "island": index,
                "ring": geographic_ring(orient(part, sign=1.0).exterior),
            })
    return {
        "type": "FeatureCollection",
        "features": features,
        "landxml": {
            "format": "landxml-cesium-footprint-v1",
            "surface": name,
            "horizontal_crs": crs.to_string(),
            "area_square_meters": footprint.area,
            "island_count": len(polygons),
            "hole_count": sum(len(polygon.interiors) for polygon in polygons),
            "zero_area_faces_excluded": zero_area,
            "warnings": [
                "2D footprint only: coordinates are longitude/latitude degrees; no elevation datum conversion.",
                "Boundary vertices are transformed without simplification; geographic edges join those vertices.",
                "Horizontal datum accuracy depends on available PROJ operations/grids.",
                "Hole-bearing islands are partitioned into hole-free triangles for Cesium Unreal. "
                "Add ALL pieces to the same Polygon Raster Overlay; holes are gaps, not clipping polygons.",
            ],
        },
        "cesium_unreal": {
            "pieces": pieces,
            "piece_count": len(pieces),
        },
    }
