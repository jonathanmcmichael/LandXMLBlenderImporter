# LandXML TIN Importer for Blender

A small Blender 4.2+ extension for importing Civil 3D LandXML TIN surfaces without retriangulating them.

The importer treats the LandXML `<P>` point coordinates and `<F>` point-ID references as authoritative. Civil coordinates are mapped from `Northing, Easting, Elevation` to Blender `X = Easting`, `Y = Northing`, `Z = Elevation`. By default, one shared horizontal origin is subtracted from every surface in the file so large-coordinate precision is manageable while surfaces retain their relative placement.

## Project layout

```text
landxml_importer/
  blender_manifest.toml  Blender extension metadata
  __init__.py            Blender operator and menu registration
  landxml.py             Blender-independent parser and coordinate conversion
  blender_import.py      Mesh creation and geospatial custom properties
tests/
  fixtures/              Small, reviewable LandXML samples
  test_landxml.py        Parser and conversion tests runnable without Blender
```

This is intentionally only three extension files. The XML/domain code stays independent of `bpy`, while the operator remains thin and Blender-specific.

## Import behavior

- Preserves the source `<F>` triangulation; it does not generate a new TIN.
- Imports all valid TIN surfaces in the file.
- Uses one shared origin so separate surfaces remain aligned.
- Stores the original origin and source-unit metadata as Blender object custom properties.
- Supports meters, international feet, and US survey feet as source units.
- Converts imported coordinates to meters, matching Blender's conventional unit scale.
- Leaves elevation unshifted by default while shifting Easting and Northing near zero.
- Groups each import's surfaces into a new Blender Collection named `LandXML_<filename>`, so repeated imports stay organized instead of dumping loose objects into the scene.

## Test outside Blender

From the repository root:

```powershell
python -m unittest discover -s tests -v
```

## Build and install

With Blender available on your command line:

```powershell
blender --command extension validate --source-dir landxml_importer
blender --command extension build --source-dir landxml_importer
```

Install the resulting ZIP through Blender's **Preferences → Extensions → Install from Disk**. The command appears under **File → Import → LandXML TIN Surface (.xml)**.

## Current boundary

The initial version assumes the common Civil 3D point order `Northing Easting Elevation`. Automatic coordinate-system discovery, breaklines, boundaries, and LandXML features other than authoritative TIN points/faces are deliberately out of scope.

Boundary clipping is intentionally not handled separately: Civil 3D bakes any applied surface boundary into which triangles appear in `<F>`, so the authoritative face list already reflects the correct clipped shape without needing to parse `<Boundaries>`.

## Verified against a real export

Validated against a real Civil 3D 2027 export (single TIN surface, 55k points, 110k faces, declared US Survey Feet, no `<CoordinateSystem>`): parses in well under a second, unit conversion matches the file's own `elevMax`/`elevMin` metadata exactly, and the imported mesh renders as a coherent, correctly oriented finished-grade surface with zero invalid faces. Multi-surface shared-origin alignment is currently only exercised by the synthetic `tests/fixtures/two_surfaces.xml` fixture — a real multi-surface export hasn't been tested yet.

