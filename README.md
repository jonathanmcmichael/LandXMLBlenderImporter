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
- Orients every triangle's normal upward and applies angle-based smooth shading. LandXML's `<F>` triangles don't guarantee winding, so each face's correct orientation is decided from its own geometry (a TIN is a heightfield — one elevation per Easting/Northing, so there are no true overhangs) rather than from neighbor-consistency algorithms, which can miss isolated triangulation islands that meet neighbors only at a single vertex — common around the long sliver triangles TINs produce.

## Test outside Blender

From the repository root:

```powershell
python -m unittest discover -s tests -v
```

## Build and install

One command rebuilds the extension and installs/enables it in Blender:

```powershell
pwsh scripts/install_extension.ps1
```

This assumes the Microsoft Store install of Blender, using the `blender-launcher.exe` execution alias (the standard `blender.exe` path under `WindowsApps` is ACL-protected and can't be run directly). Edit `$blenderAlias` in the script if Blender is installed a different way. **Restart Blender** (or disable/re-enable the extension in Preferences) afterward — it won't hot-reload an already-enabled extension's code.

To do it manually instead:

```powershell
blender --command extension validate --source-dir landxml_importer
blender --command extension build --source-dir landxml_importer
```

Install the resulting ZIP through Blender's **Preferences → Extensions → Install from Disk**. Either way, the command appears under **File → Import → LandXML TIN Surface (.xml)**.

## Current boundary

The default point order is `Northing Easting Elevation` per the LandXML 1.2 standard, but this is exposed as an import option (`Point Order`) since some real-world exports reverse it — if a terrain looks mirrored or rotated 90°, switch it. Automatic coordinate-system discovery, breaklines, boundaries, and LandXML features other than authoritative TIN points/faces are deliberately out of scope.

Boundary clipping is intentionally not handled separately: Civil 3D bakes any applied surface boundary into which triangles appear in `<F>`, so the authoritative face list already reflects the correct clipped shape without needing to parse `<Boundaries>`.

Long, thin ("sliver") triangles from the source TIN are left as-is rather than remeshed. They're geometrically valid — they represent genuinely dense point layout along linear features (curbs, centerlines, swales) — and tested edge-flip-only cleanup (Blender's Beautify Faces) barely helps: on the real 55k-point sample it reduced sliver triangles by only ~1.2%, because flipping the diagonal of an already-thin quad doesn't change the fact that all four of its points lie in a thin strip. Fixing this for real would require lossy simplification (decimation) or full retriangulation, both of which move away from exact point preservation, so they're left as a deliberate non-goal for now.

## Verified against a real export

Validated against a real Civil 3D 2027 export (single TIN surface, 55k points, 110k faces, declared US Survey Feet, no `<CoordinateSystem>`): parses in well under a second, unit conversion matches the file's own `elevMax`/`elevMin` metadata exactly, and the imported mesh renders as a coherent, correctly oriented finished-grade surface with zero invalid faces. Multi-surface shared-origin alignment is currently only exercised by the synthetic `tests/fixtures/two_surfaces.xml` fixture — a real multi-surface export hasn't been tested yet.

