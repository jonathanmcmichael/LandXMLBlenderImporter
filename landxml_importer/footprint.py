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
    edge_offset_meters: float = 0.0,
    simplify_meters: float = 0.0,
) -> dict:
    """Union raw visible faces in local meters; never use a hull or fill holes.

    edge_offset_meters shrinks (negative) or grows (positive) the exact footprint;
    simplify_meters then removes boundary vertices that deviate less than that
    distance. An inward offset at least as large as the simplify tolerance keeps
    the cutout entirely inside the TIN.
    """
    if not horizontal_epsg.strip():
        raise ValueError("Select the source projected CRS before exporting a Cesium footprint")
    if not math.isfinite(edge_offset_meters):
        raise ValueError("Edge offset must be finite meters")
    if not math.isfinite(simplify_meters) or simplify_meters < 0:
        raise ValueError("Simplify tolerance must be zero or positive meters")
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
    exact = union_all(triangles)
    if exact.geom_type not in {"Polygon", "MultiPolygon"} or not exact.is_valid:
        raise ValueError("Visible triangles did not produce a valid polygon footprint")
    footprint = exact
    if edge_offset_meters:
        footprint = footprint.buffer(edge_offset_meters, join_style="mitre", mitre_limit=2.0)
    if simplify_meters:
        footprint = footprint.simplify(simplify_meters, preserve_topology=True)
    if footprint.is_empty:
        raise ValueError("Edge offset/simplification removed the entire footprint; use smaller values")
    if footprint.geom_type not in {"Polygon", "MultiPolygon"} or not footprint.is_valid:
        raise ValueError("Edge offset/simplification did not produce a valid polygon footprint")
    if edge_offset_meters <= -simplify_meters and not exact.buffer(1e-6).contains(footprint):
        raise ValueError("Inward-offset footprint unexpectedly extends outside the TIN")
    exact_island_count = 1 if exact.geom_type == "Polygon" else len(exact.geoms)
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
    result = {
        "type": "FeatureCollection",
        "features": features,
        "landxml": {
            "format": "landxml-cesium-footprint-v1",
            "surface": name,
            "horizontal_crs": crs.to_string(),
            "area_square_meters": footprint.area,
            "exact_area_square_meters": exact.area,
            "edge_offset_meters": edge_offset_meters,
            "simplify_meters": simplify_meters,
            "exact_island_count": exact_island_count,
            "boundary_vertex_count": sum(
                len(polygon.exterior.coords) - 1 + sum(len(ring.coords) - 1 for ring in polygon.interiors)
                for polygon in polygons
            ),
            "island_count": len(polygons),
            "hole_count": sum(len(polygon.interiors) for polygon in polygons),
            "zero_area_faces_excluded": zero_area,
            "warnings": [
                "2D footprint only: coordinates are longitude/latitude degrees; no elevation datum conversion.",
                (
                    "Boundary is the exact visible TIN edge; geographic edges join its transformed vertices."
                    if not (edge_offset_meters or simplify_meters) else
                    f"Boundary is the TIN edge offset by {edge_offset_meters:g} m and simplified within "
                    f"{simplify_meters:g} m; it is no longer the exact TIN edge."
                ),
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
    if len(polygons) != exact_island_count:
        result["landxml"]["warnings"].append(
            f"Edge offset/simplification changed the island count from {exact_island_count} to "
            f"{len(polygons)}; small or narrow TIN areas may no longer be clipped."
        )
    return result
