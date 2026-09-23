# LandXML TIN Importer for Blender

A Blender 4.2+ extension for importing Civil 3D LandXML TIN surfaces without retriangulating them. Tested with Blender 5.2.2 LTS.

The importer treats the LandXML `<P>` point coordinates and `<F>` point-ID references as authoritative. Civil coordinates are mapped from `Northing, Easting, Elevation` to Blender `X = Easting`, `Y = Northing`, `Z = Elevation`. By default, one shared horizontal origin is subtracted from every surface in the file so large-coordinate precision is manageable while surfaces retain their relative placement.

## Requirements

- Blender 4.2 or later. Blender 5.2.2 LTS is the tested version.
- A LandXML file containing one or more TIN `<Surface>` elements with `<P>` points and triangular `<F>` faces.
- PowerShell and a locally installed Blender executable when using the Windows install script.

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
- Preserves valid source triangle point order and winding; it does not correct normals or apply smooth shading.
- Imports all valid TIN surfaces in the file.
- Uses one shared origin so separate surfaces remain aligned.
- Stores original origin, source-unit, source-file hash, and integrity metadata as Blender object custom properties.
- Supports meters, international feet, and US survey feet as source units.
- Converts imported coordinates to meters, matching Blender's conventional unit scale.
- Leaves elevation unshifted by default while shifting Easting and Northing near zero.
- Groups each import's surfaces into a new Blender Collection named `LandXML_<filename>`, so repeated imports stay organized instead of dumping loose objects into the scene.
- Locks object location, rotation, and scale after import to reduce accidental transform edits.

## Import workflow

1. Choose **File → Import → LandXML TIN Surface (.xml)**.
2. Select the `.xml` or `.landxml` file.
3. Choose **Source Units** to match the coordinate units in the export. The default is US survey feet.
4. Keep **Shift Near Origin** enabled unless source-coordinate placement near Blender's global origin is required.
5. Enable **Use Survey Pivot** to enter a known source-coordinate Easting, Northing, and Elevation. Mesh vertices are located relative to this pivot while the exact source coordinates remain in custom properties.
6. Keep **Validate Original TIN Faces** enabled to cancel the complete import if Blender's created vertex or face counts differ from the parsed source data.
7. Use **Northing, Easting, Elevation** point order for standard LandXML 1.2 files. Try **Easting, Northing, Elevation** only when an imported terrain is mirrored or rotated.
8. Review the **LandXML Import Validation** popup for the imported surface, vertex, and face totals plus any skipped or degenerate source faces.

The import creates a `LandXML_<filename>` collection. Each surface object records its source path and SHA-256 digest, selected units, point order, origin, vertex count, face count, skipped-face diagnostics, degenerate-face count, and raw geometry fingerprint in Blender custom properties.

## Supported input and limitations

- Tested with a Civil 3D 2027 LandXML export and standard LandXML 1.2 `Northing Easting Elevation` point order.
- Source units can be meters, international feet, or US survey feet. The imported mesh is converted to meters.
- TIN faces must contain exactly three point IDs. Non-triangular records are skipped rather than truncated, and their reason is recorded in `landxml_skipped_face_reasons`.
- Faces with unresolved point IDs are skipped; their count and reason are also recorded in `landxml_skipped_face_reasons`.
- Zero-area, repeated-vertex, and collinear source triangles are retained without modification and counted in `landxml_degenerate_face_count`.
- The importer does not automatically discover coordinate reference systems, parse breaklines, or independently apply boundaries. Civil 3D boundary clipping is represented by the authoritative `<F>` list.

## TIN integrity

LandXML points and triangles are authoritative. The importer does not retriangulate, fill disconnected islands, merge vertices, change face winding, or modify normals and shading. A strict import is atomic: if parsing or original-face validation fails, the new collection and its meshes are removed rather than leaving a partial result.

Use **Object → Validate LandXML TIN Integrity** to compare the selected object's raw mesh coordinates and polygon loops against the stored import fingerprint. This intentionally ignores transforms and modifier output; it detects changes to the base mesh data itself. Object transforms are locked after import, but Blender Edit Mode, modifiers, and Python scripts can still alter a mesh. The validator identifies that divergence; it cannot prevent it.

To recover a source coordinate from a local mesh vertex, divide its Blender coordinate by `landxml_unit_to_meters` and add `landxml_origin_easting`, `landxml_origin_northing`, and `landxml_origin_elevation` respectively. Pivot values use the selected source-unit system.

## Test outside Blender

From the repository root:

```powershell
python -m unittest discover -s tests -v
```

## Build and install

One command rebuilds the extension and installs/enables it in Blender on Windows:

```powershell
pwsh scripts/install_extension.ps1
```

The script checks the standard Blender Foundation installation at `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` first and then the Microsoft Store execution alias. Add another path to `blenderCandidates` in [scripts/install_extension.ps1](scripts/install_extension.ps1) when Blender is installed elsewhere. **Restart Blender** (or disable/re-enable the extension in Preferences) afterward; Blender will not hot-reload an already-enabled extension's code.

To do it manually instead:

```powershell
blender --command extension validate landxml_importer
blender --command extension build --source-dir landxml_importer
```

Install the resulting ZIP through Blender's **Preferences → Extensions → Install from Disk**. Either way, the command appears under **File → Import → LandXML TIN Surface (.xml)**.

## Support

Use [GitHub Issues](https://github.com/jonathanmcmichael/LandXMLBlenderImporter/issues) for reproducible bugs and compatibility reports. Do not attach confidential project LandXML files; use a minimal sanitized sample when one is needed to reproduce an issue.

## License

This project is licensed under the GNU General Public License v3.0 or later. See `LICENSE`.

## Design boundaries

The default point order is `Northing Easting Elevation` per the LandXML 1.2 standard, but this is exposed as an import option (`Point Order`) since some real-world exports reverse it. Automatic coordinate-system discovery and LandXML features other than authoritative TIN points/faces are deliberately out of scope.

Long, thin ("sliver") triangles from the source TIN are left as-is rather than remeshed. They can represent dense point layout along linear features such as curbs, centerlines, and swales. Fixing them would require lossy simplification or full retriangulation, both of which conflict with exact point and face preservation.

## Verified against a real export

Validated against a real Civil 3D 2027 export (single TIN surface, 55k points, 110k faces, declared US Survey Feet, no `<CoordinateSystem>`): parses in well under a second, unit conversion matches the file's own `elevMax`/`elevMin` metadata exactly, and the imported mesh renders as a coherent, correctly oriented finished-grade surface with zero invalid faces. Multi-surface shared-origin alignment is currently only exercised by the synthetic `tests/fixtures/two_surfaces.xml` fixture — a real multi-surface export hasn't been tested yet.
