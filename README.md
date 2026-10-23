# LandXML Importer for Blender

A Blender 5.2+ extension for importing LandXML TINs and useful civil linework into Blender. Tested with Blender 5.2.2 LTS.

The importer converts LandXML surface points/faces, boundaries, breaklines, PlanFeatures, generic `CoordGeom` linework, pipes, CgPoints, and Locations to Blender geometry. It stores every source element, namespace, attribute, text value, and child order in indexed JSONL Blender Text datablocks referenced by the import collection. Civil coordinates map from `Northing, Easting, Elevation` to Blender `X = Easting`, `Y = Northing`, `Z = Elevation`.

## Requirements

- Blender 5.2 or later (Python 3.13). Blender 5.2.2 LTS is the tested version.
- The extension bundles Shapely 2.1.2 wheels for boundary clipping on Windows x64, Linux x64/arm64, and macOS x64/arm64.
- A valid LandXML 1.2 document; files with or without supported geometry are retained as structured records.
- PowerShell and a locally installed Blender executable when using the Windows install script.

## Project layout

```text
landxml_importer/
  blender_manifest.toml  Blender extension metadata
  __init__.py            Blender operator and menu registration
  landxml.py             Blender-independent parser and coordinate conversion
  georef.py              Blender-independent GeoTIFF / world-file georeferencing
  blender_import.py      Mesh/curve creation, structured metadata, orthophoto UVs
  wheels/                Shapely geometry wheels for Blender's supported Python ABIs
tests/
  fixtures/              Small, reviewable LandXML samples
  fixtures/landxml-1.2.xsd  Pinned official XSD for coverage checks
  test_landxml.py        Parser and conversion tests runnable without Blender
  test_landxml_schema.py XSD-backed metadata/adapter coverage
  test_georef.py         Georeferencing and UV-mapping tests runnable without Blender
```

The XML/domain and georeferencing code stays independent of `bpy`, while the operators remain thin and Blender-specific.

## Import behavior

- Preserves original `<P>` and `<F>` records and IDs in the structured metadata Text datablock.
- Applies `edgeTrim="true"` outer and hide boundary loops to the working TIN by intersecting and retriangulating affected faces; generated elevations are interpolated from source triangles.
- Imports boundaries, breaklines, PlanFeatures, pipe centerlines, and `CoordGeom` lines/arcs as separate Blender curve objects; CgPoints and Locations become categorized point-cloud meshes with source IDs/descriptions as point attributes.
- Imports all valid TIN surfaces in the file.
- Uses one shared origin for georeferenced surfaces and linework so they remain aligned; station/offset geometry stays local.
- Stores the complete structured LandXML tree in an indexed JSON Text datablock plus bounded JSONL Text chunks and links them from the import collection and created objects.
- Stores source and output face counts, boundary-affected face counts, source-unit, source-file hash, and output geometry fingerprints as custom properties.
- Supports millimeters, centimeters, meters, kilometers, inches, international feet, US survey feet, and international/US survey miles as source units.
- Reads declared units automatically; generic `foot` defaults to US survey feet with a warning and can be overridden.
- Converts imported coordinates to meters, matching Blender's conventional unit scale.
- Leaves elevation unshifted by default while shifting Easting and Northing near zero.
- Groups each import into `LandXML_<filename>` with separate collections for surfaces, points, boundaries, breaklines, PlanFeatures, and additional linework categories.
- Locks object location, rotation, and scale after import to reduce accidental transform edits.

## Import workflow

1. Choose **File → Import → LandXML Data (.xml)**.
2. Select the `.xml` or `.landxml` file.
3. Leave **Source Units** set to **From LandXML** to use declared units. Generic `foot` and missing unit declarations warn and default to US survey feet; select an explicit override when needed.
4. Keep **Shift Near Origin** enabled unless source-coordinate placement near Blender's global origin is required.
5. Enable **Use Survey Pivot** to enter a known source-coordinate Easting, Northing, and Elevation. Mesh vertices are located relative to this pivot while the exact source coordinates remain in custom properties.
6. Keep **Validate Imported Geometry** enabled to cancel the complete import if Blender's mesh differs from the planned clipped output.
7. Use **Northing, Easting, Elevation** point order for standard LandXML 1.2 files. Try **Easting, Northing, Elevation** only when an imported terrain is mirrored or rotated.
8. Review the validation popup for source/output face counts, clipped source faces, linework objects, units, and skipped or degenerate faces.

The import creates a `LandXML_<filename>` collection plus a `LandXML_<filename>_metadata.json` index Text datablock and bounded JSONL record chunks. Each record stores its source node ID, parent ID, sibling order, name, namespace, attributes, text, and mixed-content tail. Mesh, curve, and point-cloud objects link to the index. Rebuild the full source tree by joining records through their parent and child indices.

## Supported input and limitations

- Tested with a Civil 3D 2027 LandXML export and standard LandXML 1.2 `Northing Easting Elevation` point order.
- Source units cover all eight LandXML 1.2 metric and imperial linear-unit values; generic feet default to US survey feet with an override warning. International feet are also available as an explicit override. All imported geometry is converted to meters.
- TIN faces must contain exactly three point IDs. Non-triangular records are skipped rather than truncated, and their reason is recorded in `landxml_skipped_face_reasons`.
- Faces with unresolved point IDs are skipped; their count and reason are also recorded in `landxml_skipped_face_reasons`.
- Zero-area, repeated-vertex, and collinear source triangles are retained without modification and counted in `landxml_degenerate_face_count`.
- All LandXML records are retained in structured metadata. Dedicated geometry adapters cover TIN surfaces, boundaries, breaklines, CgPoints, Locations, pipes, profiles, cross-sections, PlanFeatures, and `CoordGeom` lines/circular curves; other standard entities remain available as structured records but do not yet have specialized Blender geometry adapters.
- Coordinate reference system discovery/reprojection is not performed. The source coordinate-system records are retained in metadata.
- Circular `CoordGeom` arcs are sampled at five-degree maximum angular intervals for Blender curve geometry; source arc parameters remain in metadata.

## TIN integrity

LandXML points/faces remain the source records. When an edge-trim boundary is active, the working mesh is clipped and retriangulated only where needed; generated vertex elevations are interpolated from their source triangle. Source face records remain in structured metadata, while the mesh fingerprint covers the resulting Blender geometry. A strict import is atomic: if parsing or output-geometry validation fails, created objects and the collection are removed rather than leaving a partial result.

Use **Object → Validate LandXML TIN Integrity** to compare the selected object's raw mesh coordinates and polygon loops against the stored import fingerprint. This intentionally ignores transforms and modifier output; it detects changes to the base mesh data itself. Object transforms are locked after import, but Blender Edit Mode, modifiers, and Python scripts can still alter a mesh. The validator identifies that divergence; it cannot prevent it.

To recover a source coordinate from a local mesh vertex, divide its Blender coordinate by `landxml_unit_to_meters` and add `landxml_origin_easting`, `landxml_origin_northing`, and `landxml_origin_elevation` respectively. Pivot values use the selected source-unit system.

## Using breaklines on the TIN

Select an imported surface and choose **Object → Use Breaklines on Surface**. The dialog can mark matching TIN edges sharp, mark them as UV seams, or do both. Sharp marking enables smooth shading on the surface by default so the sharp edges affect the visible normals. The tolerance is in meters and defaults to 0.1 mm.

This operation does not change topology or create edges. It only marks existing TIN edges whose endpoints match breakline segments. Blender reports how many segments matched and how many do not coincide with mesh edges; unmatched segments are left as curves and need a topology edit or retriangulation to become mesh edges. On the supplied Civil 3D export, 121,213 of 129,574 breakline segments matched at the default tolerance.

## Draping a georeferenced orthophoto (e.g. DroneDeploy)

Select one or more imported surfaces and choose **Object → Apply Georeferenced Orthophoto**. Each vertex is mapped back to its source Easting/Northing and projected top-down into the image, creating an `Ortho` UV map and a `LandXML_Ortho_<image>` material. Raw vertices and faces are not modified, so the integrity validator still passes.

Placement is read from internal GeoTIFF tags (classic TIFF or BigTIFF), or from a sidecar world file (`.tfw`, `.jgw`, `.pgw`, `.wld`). The image must:

- Use the **same projected CRS and linear units** as the LandXML. When the GeoTIFF declares its units they are checked against the surface's source units; geographic (lat/long) and Web Mercator images are rejected.
- Be north-up (no rotation or skew).
- Be readable and reasonably sized for Blender. Large DroneDeploy orthomosaics should be reprojected and downsampled first, for example:

```powershell
gdalwarp -t_srs EPSG:XXXX -r bilinear ortho.tif ortho_proj.tif
gdal_translate -of JPEG -b 1 -b 2 -b 3 -outsize 16384 0 -co QUALITY=92 -co WORLDFILE=YES ortho_proj.tif ortho.jpg
```

If the Civil 3D project uses scaled ground coordinates or a local site calibration, a CRS reprojection alone will not align the image. The operator warns when vertices fall outside the image and refuses when none fall inside. Horizontal placement is exact; the orthophoto was rectified to the drone's own surface model, so above-ground features such as trees and buildings will appear painted onto the TIN.

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
blender --command extension build --source-dir landxml_importer --split-platforms
```

The build writes one ZIP per platform (for example `landxml_tin_importer-0.3.0-windows_x64.zip`), each containing only that platform's Shapely wheel. Install the ZIP for your platform through Blender's **Preferences → Extensions → Install from Disk**. Either way, the command appears under **File → Import → LandXML Data (.xml)**.

## Support

Use [GitHub Issues](https://github.com/jonathanmcmichael/LandXMLBlenderImporter/issues) for reproducible bugs and compatibility reports. Do not attach confidential project LandXML files; use a minimal sanitized sample when one is needed to reproduce an issue.

## License

This project is licensed under the GNU General Public License v3.0 or later. See `LICENSE`.

## Design boundaries

The default point order is `Northing Easting Elevation` per the LandXML 1.2 standard, but this is exposed as an import option (`Point Order`) since some real-world exports reverse it. Automatic coordinate-system discovery and reprojection remain out of scope.

Long, thin ("sliver") triangles from the source TIN are left as-is rather than remeshed. They can represent dense point layout along linear features such as curbs, centerlines, and swales. Fixing them would require lossy simplification or full retriangulation, both of which conflict with exact point and face preservation.

## Verified against a real export

Validated against a real Civil 3D 2027 export (single TIN surface, 55k points, 110k faces, declared US Survey Feet, no `<CoordinateSystem>`): parses in well under a second, unit conversion matches the file's own `elevMax`/`elevMin` metadata exactly, and the imported mesh renders as a coherent, correctly oriented finished-grade surface with zero invalid faces. Multi-surface shared-origin alignment is currently only exercised by the synthetic `tests/fixtures/two_surfaces.xml` fixture — a real multi-surface export hasn't been tested yet.
