"""Blender-independent orthophoto georeferencing from GeoTIFF tags or world files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import BinaryIO, Iterable


class GeoreferenceError(ValueError):
    """Raised when an image cannot be placed exactly in source coordinates."""


@dataclass(frozen=True)
class ImageBounds:
    """Outer pixel-edge extents of a north-up image in its CRS units."""

    left: float
    top: float
    right: float
    bottom: float
    linear_units: str | None = None
    source: str = ""


_TAG_IMAGE_WIDTH = 256
_TAG_IMAGE_LENGTH = 257
_TAG_MODEL_PIXEL_SCALE = 33550
_TAG_MODEL_TIEPOINT = 33922
_TAG_MODEL_TRANSFORMATION = 34264
_TAG_GEO_KEY_DIRECTORY = 34735

_KEY_MODEL_TYPE = 1024
_KEY_RASTER_TYPE = 1025
_KEY_PROJECTED_CS = 3072
_KEY_PROJ_LINEAR_UNITS = 3076

_MODEL_TYPE_GEOGRAPHIC = 2
_RASTER_PIXEL_IS_POINT = 2
_WEB_MERCATOR_CODES = {3857, 3785, 900913}
_EPSG_LINEAR_UNITS = {9001: "METERS", 9002: "INTERNATIONAL_FEET", 9003: "US_SURVEY_FEET"}

# type id -> (struct code, byte size)
_TIFF_TYPES = {
    1: ("B", 1), 3: ("H", 2), 4: ("I", 4), 11: ("f", 4),
    12: ("d", 8), 16: ("Q", 8), 17: ("q", 8),
}

WORLD_FILE_SUFFIXES = {
    ".tif": (".tfw", ".tifw", ".wld"),
    ".tiff": (".tfw", ".tiffw", ".wld"),
    ".jpg": (".jgw", ".jpgw", ".wld"),
    ".jpeg": (".jgw", ".jpegw", ".wld"),
    ".png": (".pgw", ".pngw", ".wld"),
}


def _read_tiff_tags(handle: BinaryIO, wanted: Iterable[int]) -> dict[int, tuple]:
    """Read selected tags from the first IFD of a classic or BigTIFF file."""
    wanted = set(wanted)
    header = handle.read(16)
    if header[:2] == b"II":
        order = "<"
    elif header[:2] == b"MM":
        order = ">"
    else:
        raise GeoreferenceError("Not a TIFF file")

    version = struct.unpack(order + "H", header[2:4])[0]
    if version == 42:
        ifd_offset = struct.unpack(order + "I", header[4:8])[0]
        count_fmt, entry_fmt, entry_size, inline_size = "H", "HHI4s", 12, 4
    elif version == 43:
        ifd_offset = struct.unpack(order + "Q", header[8:16])[0]
        count_fmt, entry_fmt, entry_size, inline_size = "Q", "HHQ8s", 20, 8
    else:
        raise GeoreferenceError(f"Unsupported TIFF version {version}")

    handle.seek(ifd_offset)
    count_size = struct.calcsize(count_fmt)
    entry_count = struct.unpack(order + count_fmt, handle.read(count_size))[0]
    entries = handle.read(entry_count * entry_size)

    tags: dict[int, tuple] = {}
    for index in range(entry_count):
        raw = entries[index * entry_size:(index + 1) * entry_size]
        tag, type_id, count, payload = struct.unpack(order + entry_fmt, raw)
        if tag not in wanted or type_id not in _TIFF_TYPES:
            continue
        code, size = _TIFF_TYPES[type_id]
        length = size * count
        if length <= inline_size:
            data = payload[:length]
        else:
            offset = struct.unpack(order + ("I" if inline_size == 4 else "Q"), payload)[0]
            handle.seek(offset)
            data = handle.read(length)
        tags[tag] = struct.unpack(order + code * count, data)
    return tags


def _geo_keys(directory: tuple) -> dict[int, int]:
    """Return inline SHORT GeoKeys; referenced (double/ASCII) keys are ignored."""
    keys = {}
    for index in range(directory[3]):
        key_id, location, _count, value = directory[4 + index * 4:8 + index * 4]
        if location == 0:
            keys[key_id] = value
    return keys


def read_geotiff_bounds(path: str | Path) -> ImageBounds | None:
    """Return bounds from internal GeoTIFF tags, or None when the TIFF is not georeferenced."""
    with open(path, "rb") as handle:
        tags = _read_tiff_tags(
            handle,
            (
                _TAG_IMAGE_WIDTH, _TAG_IMAGE_LENGTH, _TAG_MODEL_PIXEL_SCALE,
                _TAG_MODEL_TIEPOINT, _TAG_MODEL_TRANSFORMATION, _TAG_GEO_KEY_DIRECTORY,
            ),
        )

    width = tags.get(_TAG_IMAGE_WIDTH, (0,))[0]
    height = tags.get(_TAG_IMAGE_LENGTH, (0,))[0]
    keys = _geo_keys(tags[_TAG_GEO_KEY_DIRECTORY]) if _TAG_GEO_KEY_DIRECTORY in tags else {}

    if keys.get(_KEY_MODEL_TYPE) == _MODEL_TYPE_GEOGRAPHIC:
        raise GeoreferenceError(
            "GeoTIFF uses geographic (latitude/longitude) coordinates; reproject it to the LandXML's projected CRS"
        )
    if keys.get(_KEY_PROJECTED_CS) in _WEB_MERCATOR_CODES:
        raise GeoreferenceError(
            "GeoTIFF uses Web Mercator, which distorts survey distances; reproject it to the LandXML's projected CRS"
        )

    if _TAG_MODEL_TRANSFORMATION in tags:
        matrix = tags[_TAG_MODEL_TRANSFORMATION]
        if matrix[1] != 0.0 or matrix[4] != 0.0:
            raise GeoreferenceError("Rotated or skewed GeoTIFFs are not supported; warp it north-up first")
        scale_x, scale_y = matrix[0], -matrix[5]
        left, top = matrix[3], matrix[7]
    elif _TAG_MODEL_TIEPOINT in tags and _TAG_MODEL_PIXEL_SCALE in tags:
        tie = tags[_TAG_MODEL_TIEPOINT]
        scale_x, scale_y = tags[_TAG_MODEL_PIXEL_SCALE][:2]
        left = tie[3] - tie[0] * scale_x
        top = tie[4] + tie[1] * scale_y
    else:
        return None

    if keys.get(_KEY_RASTER_TYPE) == _RASTER_PIXEL_IS_POINT:
        left -= scale_x / 2.0
        top += scale_y / 2.0

    return _bounds(left, top, scale_x, scale_y, width, height,
                   _EPSG_LINEAR_UNITS.get(keys.get(_KEY_PROJ_LINEAR_UNITS)), str(path))


def find_world_file(image_path: str | Path) -> Path | None:
    image_path = Path(image_path)
    suffixes = WORLD_FILE_SUFFIXES.get(image_path.suffix.lower(), (".wld",))
    for suffix in suffixes:
        for candidate in (image_path.with_suffix(suffix), image_path.with_suffix(suffix.upper())):
            if candidate.is_file():
                return candidate
    return None


def read_world_file(path: str | Path, width: int, height: int) -> ImageBounds:
    """Return bounds from a six-line ESRI world file, whose origin is the upper-left pixel centre."""
    values = [float(line) for line in Path(path).read_text().split()]
    if len(values) != 6:
        raise GeoreferenceError(f"World file {path} must contain exactly six numbers")
    scale_x, rot_y, rot_x, neg_scale_y, centre_x, centre_y = values
    if rot_x != 0.0 or rot_y != 0.0:
        raise GeoreferenceError("Rotated or skewed world files are not supported; warp the image north-up first")
    scale_y = -neg_scale_y
    return _bounds(centre_x - scale_x / 2.0, centre_y + scale_y / 2.0,
                   scale_x, scale_y, width, height, None, str(path))


def _bounds(left, top, scale_x, scale_y, width, height, units, source) -> ImageBounds:
    if scale_x <= 0.0 or scale_y <= 0.0:
        raise GeoreferenceError("Image must be north-up with positive pixel size")
    if width <= 0 or height <= 0:
        raise GeoreferenceError("Image dimensions are unknown")
    return ImageBounds(left, top, left + width * scale_x, top - height * scale_y, units, source)


def resolve_bounds(image_path: str | Path, width: int, height: int) -> ImageBounds:
    """Prefer internal GeoTIFF tags (as GDAL does), then fall back to a sidecar world file."""
    image_path = Path(image_path)
    if image_path.suffix.lower() in (".tif", ".tiff"):
        bounds = read_geotiff_bounds(image_path)
        if bounds is not None:
            return bounds
    world_file = find_world_file(image_path)
    if world_file is None:
        raise GeoreferenceError(f"{image_path.name} has no GeoTIFF georeference or world file")
    return read_world_file(world_file, width, height)


def planar_uvs(
    local_xy: Iterable[tuple[float, float]],
    bounds: ImageBounds,
    *,
    origin: tuple[float, float],
    unit_to_meters: float,
) -> list[tuple[float, float]]:
    """Map local Blender X/Y (meters from origin) to image UVs via source coordinates."""
    width = bounds.right - bounds.left
    height = bounds.top - bounds.bottom
    return [
        (
            (x / unit_to_meters + origin[0] - bounds.left) / width,
            (y / unit_to_meters + origin[1] - bounds.bottom) / height,
        )
        for x, y in local_xy
    ]
