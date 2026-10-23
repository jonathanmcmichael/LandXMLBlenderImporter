from pathlib import Path
import struct
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "landxml_importer"))

from georef import (  # noqa: E402
    GeoreferenceError,
    ImageBounds,
    planar_uvs,
    read_geotiff_bounds,
    read_world_file,
    resolve_bounds,
)

SHORT, LONG, DOUBLE = 3, 4, 12
_CODES = {SHORT: ("H", 2), LONG: ("I", 4), DOUBLE: ("d", 8)}


def _write_tiff(path: Path, entries: list[tuple[int, int, tuple]], *, big: bool = False) -> None:
    """Write a header-and-IFD-only TIFF; pixel data is irrelevant to georeferencing."""
    order = "<"
    entries = sorted(entries)
    if big:
        header = b"II" + struct.pack(order + "HHHQ", 43, 8, 0, 16)
        count_fmt, entry_size, inline, offset_fmt = "Q", 20, 8, "Q"
    else:
        header = b"II" + struct.pack(order + "HI", 42, 8)
        count_fmt, entry_size, inline, offset_fmt = "H", 12, 4, "I"
    ifd_start = len(header)
    data_start = ifd_start + struct.calcsize(count_fmt) + entry_size * len(entries) + inline
    ifd = struct.pack(order + count_fmt, len(entries))
    extra = b""
    for tag, type_id, values in entries:
        code, size = _CODES[type_id]
        payload = struct.pack(order + code * len(values), *values)
        if len(payload) <= inline:
            field = payload.ljust(inline, b"\0")
        else:
            field = struct.pack(order + offset_fmt, data_start + len(extra))
            extra += payload
        ifd += struct.pack(order + "HH" + ("Q" if big else "I"), tag, type_id, len(values)) + field
    ifd += b"\0" * inline
    path.write_bytes(header + ifd + extra)


def _geokeys(*keys: tuple[int, int]) -> tuple:
    directory = [1, 1, 0, len(keys)]
    for key_id, value in keys:
        directory += [key_id, 0, 1, value]
    return tuple(directory)


def _georef_entries(*keys: tuple[int, int]) -> list[tuple[int, int, tuple]]:
    return [
        (256, SHORT, (200,)),
        (257, SHORT, (100,)),
        (33550, DOUBLE, (0.5, 0.25, 0.0)),
        (33922, DOUBLE, (0.0, 0.0, 0.0, 1000.0, 2000.0, 0.0)),
        (34735, SHORT, _geokeys(*keys)),
    ]


class GeoTiffTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_tiepoint_and_pixel_scale_give_outer_edges(self):
        path = self.tmp / "ortho.tif"
        _write_tiff(path, _georef_entries((1025, 1), (3076, 9003)))
        bounds = read_geotiff_bounds(path)
        self.assertEqual((bounds.left, bounds.top, bounds.right, bounds.bottom), (1000.0, 2000.0, 1100.0, 1975.0))
        self.assertEqual(bounds.linear_units, "US_SURVEY_FEET")

    def test_bigtiff_is_supported(self):
        path = self.tmp / "ortho.tif"
        _write_tiff(path, _georef_entries((3076, 9001)), big=True)
        bounds = read_geotiff_bounds(path)
        self.assertEqual((bounds.left, bounds.bottom), (1000.0, 1975.0))
        self.assertEqual(bounds.linear_units, "METERS")

    def test_pixel_is_point_shifts_half_pixel(self):
        path = self.tmp / "ortho.tif"
        _write_tiff(path, _georef_entries((1025, 2)))
        bounds = read_geotiff_bounds(path)
        self.assertEqual((bounds.left, bounds.top), (999.75, 2000.125))

    def test_model_transformation_is_used(self):
        path = self.tmp / "ortho.tif"
        matrix = (0.5, 0.0, 0.0, 1000.0, 0.0, -0.25, 0.0, 2000.0, 0, 0, 0, 0, 0, 0, 0, 1.0)
        _write_tiff(path, [(256, SHORT, (200,)), (257, SHORT, (100,)), (34264, DOUBLE, matrix)])
        bounds = read_geotiff_bounds(path)
        self.assertEqual((bounds.right, bounds.bottom), (1100.0, 1975.0))
        self.assertIsNone(bounds.linear_units)

    def test_rotated_transformation_is_rejected(self):
        path = self.tmp / "ortho.tif"
        matrix = (0.5, 0.1, 0.0, 1000.0, 0.0, -0.25, 0.0, 2000.0, 0, 0, 0, 0, 0, 0, 0, 1.0)
        _write_tiff(path, [(256, SHORT, (200,)), (257, SHORT, (100,)), (34264, DOUBLE, matrix)])
        with self.assertRaises(GeoreferenceError):
            read_geotiff_bounds(path)

    def test_geographic_and_web_mercator_are_rejected(self):
        for keys in (((1024, 2),), ((1024, 1), (3072, 3857))):
            path = self.tmp / "ortho.tif"
            _write_tiff(path, _georef_entries(*keys))
            with self.assertRaises(GeoreferenceError):
                read_geotiff_bounds(path)

    def test_plain_tiff_falls_back_to_world_file(self):
        path = self.tmp / "ortho.tif"
        _write_tiff(path, [(256, SHORT, (200,)), (257, SHORT, (100,))])
        self.assertIsNone(read_geotiff_bounds(path))
        (self.tmp / "ortho.tfw").write_text("0.5\n0\n0\n-0.25\n1000.25\n1999.875\n")
        bounds = resolve_bounds(path, 200, 100)
        self.assertEqual((bounds.left, bounds.top, bounds.right, bounds.bottom), (1000.0, 2000.0, 1100.0, 1975.0))

    def test_missing_georeference_raises(self):
        path = self.tmp / "ortho.jpg"
        path.write_bytes(b"")
        with self.assertRaises(GeoreferenceError):
            resolve_bounds(path, 200, 100)

    def test_rotated_world_file_is_rejected(self):
        world = self.tmp / "ortho.jgw"
        world.write_text("0.5\n0.1\n0\n-0.25\n1000\n2000\n")
        with self.assertRaises(GeoreferenceError):
            read_world_file(world, 200, 100)


class PlanarUvTests(unittest.TestCase):
    def test_local_meters_map_back_through_origin_and_units(self):
        bounds = ImageBounds(left=1000.0, top=2000.0, right=1100.0, bottom=1975.0)
        uvs = planar_uvs(
            [(0.0, 0.0), (30.48, 7.62)],
            bounds,
            origin=(1000.0, 1975.0),
            unit_to_meters=0.3048,
        )
        self.assertEqual(uvs[0], (0.0, 0.0))
        self.assertAlmostEqual(uvs[1][0], 1.0)
        self.assertAlmostEqual(uvs[1][1], 1.0)


if __name__ == "__main__":
    unittest.main()
