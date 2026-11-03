"""Portable survey-pivot metadata and projected-CRS anchor conversion."""

from __future__ import annotations

import math
from functools import lru_cache

from pyproj import CRS, Proj, Transformer
from pyproj.database import query_crs_info
from pyproj.enums import PJType
from pyproj.exceptions import ProjError


NAD83_REALIZATION_PREFIXES = ("NAD83 /", "NAD83(HARN) /", "NAD83(NSRS2007) /", "NAD83(2011) /")


def _is_easting_northing(code: str) -> bool:
    return tuple(axis.direction for axis in CRS.from_epsg(code).axis_info[:2]) == ("east", "north")


@lru_cache(maxsize=1)
def us_nad83_crs_items() -> tuple[tuple[str, str, str], ...]:
    """Keep enum strings alive and use the bundled EPSG catalog, not a zone list."""
    systems = [
        info for info in query_crs_info(auth_name="EPSG", pj_types=PJType.PROJECTED_CRS)
        if info.name.startswith(NAD83_REALIZATION_PREFIXES)
        and ("United States" in info.area_of_use.name or "USA" in info.area_of_use.name)
        and _is_easting_northing(info.code)
    ]
    systems.sort(key=lambda info: (info.name.casefold(), int(info.code)))
    return (
        ("CUSTOM", "Not specified / manual EPSG", "Preserve the pivot without conversion, or enter a projected EPSG code"),
        *(
            (info.code, f"{info.name} - EPSG:{info.code}", info.area_of_use.name)
            for info in systems
        ),
    )


def search_us_nad83_crs(text: str) -> tuple[tuple[str, str], ...]:
    tokens = text.casefold().split()
    return tuple(
        (label, description)
        for _, label, description in us_nad83_crs_items()[1:]
        if all(token in label.casefold() for token in tokens)
    )


def resolve_crs_entry(text: str, manual_epsg: str = "") -> str:
    value = text.strip()
    if not value or value == "CUSTOM":
        return manual_epsg.strip()
    for code, label, _ in us_nad83_crs_items()[1:]:
        if value.casefold() in (label.casefold(), label.rsplit(" - EPSG:", 1)[0].casefold()):
            return code
    code = value.upper().removeprefix("EPSG:").strip()
    if code.isascii() and code.isdecimal():
        return code
    raise ValueError("Select a matching coordinate system or enter a numeric EPSG code (e.g. EPSG:2232)")


def parse_coordinate(value: str) -> float:
    coordinate = float(value)
    if not math.isfinite(coordinate):
        raise ValueError("Survey coordinates must be finite numbers")
    return coordinate


def projected_wgs84_transform(horizontal_epsg: str, unit_to_meters: float):
    crs = CRS.from_user_input(f"EPSG:{horizontal_epsg.strip().upper().removeprefix('EPSG:')}")
    if not crs.is_projected or len(crs.axis_info) < 2:
        raise ValueError("Select a projected EPSG code, not a latitude/longitude CRS")
    axes = crs.axis_info[:2]
    if tuple(axis.direction for axis in axes) != ("east", "north"):
        raise ValueError("Source CRS must use Easting/Northing axes")
    if axes[0].unit_conversion_factor != axes[1].unit_conversion_factor:
        raise ValueError("Source CRS horizontal axes must use the same units")
    transformer = Transformer.from_crs(
        crs, "EPSG:4326", always_xy=True, allow_ballpark=False, only_best=True,
    )
    return crs, transformer, unit_to_meters / axes[0].unit_conversion_factor


def survey_reference(
    origin: tuple[float, float, float],
    *,
    source_units: str,
    unit_to_meters: float,
    horizontal_epsg: str = "",
    vertical_datum: str = "",
    ellipsoid_height: str = "",
) -> dict:
    """Keep local grid coordinates distinct from a geographic Cesium anchor.

    An explicitly supplied WGS84 ellipsoid height is independent of the source
    elevation: a horizontal transformation cannot convert a vertical datum.
    """
    if len(origin) != 3 or not all(math.isfinite(value) for value in origin):
        raise ValueError("Survey pivot must contain three finite coordinates")
    if not math.isfinite(unit_to_meters) or unit_to_meters <= 0:
        raise ValueError("Source-unit scale must be finite and positive")
    height = parse_coordinate(ellipsoid_height) if ellipsoid_height.strip() else None
    warnings = [
        "Local vertices are projected grid offsets, not reprojected east/north/up coordinates. "
        "Account for grid convergence and projection scale when placing in Cesium.",
    ]
    reference = {
        "format": "landxml-survey-reference-v1",
        "origin": dict(zip(("easting", "northing", "elevation"), origin)),
        "source_units": source_units,
        "unit_to_meters": unit_to_meters,
        "horizontal_crs": None,
        "vertical_datum": vertical_datum.strip() or "unknown",
        "local_axes": ["grid_east", "grid_north", "up"],
        "local_units": "meters",
        "source_coordinate_formula": "source = local_meters / unit_to_meters + origin",
        "cesium_anchor": None,
        "warnings": warnings,
    }
    if not horizontal_epsg.strip():
        if height is not None:
            raise ValueError("A projected EPSG code is required with a Cesium ellipsoid height")
        warnings.append("Source CRS is unspecified; no Cesium longitude/latitude anchor is available.")
        return reference

    try:
        crs, transformer, scale = projected_wgs84_transform(horizontal_epsg, unit_to_meters)
        x, y = origin[0] * scale, origin[1] * scale
        longitude, latitude = transformer.transform(x, y, errcheck=True)
        operation = transformer.get_last_used_operation()
        geographic = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
        grid_lon, grid_lat = geographic.transform(x, y, errcheck=True)
        factors = Proj(crs).get_factors(grid_lon, grid_lat, errcheck=True)
    except ProjError as exc:
        raise ValueError(f"Cannot convert the survey pivot to WGS84: {exc}") from exc
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError("Survey pivot did not produce valid longitude/latitude")
    area = crs.area_of_use
    if area:
        inside_longitude = (
            area.west <= longitude <= area.east if area.west <= area.east
            else longitude >= area.west or longitude <= area.east
        )
        if not (inside_longitude and area.south <= latitude <= area.north):
            raise ValueError("Survey pivot is outside the selected CRS area of use; check zone, units and coordinates")
    reference["horizontal_crs"] = {"id": crs.to_string(), "name": crs.name}
    reference["horizontal_operation"] = {
        "description": operation.description,
        "reported_accuracy_meters": operation.accuracy if operation.accuracy >= 0 else None,
    }
    reference["projection"] = {
        "meridian_convergence_degrees": factors.meridian_convergence,
        "meridional_scale": factors.meridional_scale,
        "parallel_scale": factors.parallel_scale,
    }
    reference["cesium_anchor"] = {
        "crs": "EPSG:4326",
        "longitude_degrees": longitude,
        "latitude_degrees": latitude,
        "ellipsoid_height_meters": height,
        "height_datum": "WGS84 ellipsoid" if height is not None else "unknown",
    }
    warnings.append(
        "Horizontal datum accuracy depends on locally available PROJ operations/grids; "
        "verify against a surveyed WGS84 control point."
    )
    if height is None:
        warnings.append(
            "Cesium ellipsoid height is unknown. Source elevation has NOT been converted; "
            "supply the pivot's WGS84 ellipsoid height separately."
        )
    return reference
