# LandXML Importer for Blender

A Blender 5.2+ extension for importing LandXML TINs and useful civil linework into Blender. Tested with Blender 5.2.2 LTS.

The importer converts LandXML surface points/faces, boundaries, breaklines, PlanFeatures, generic `CoordGeom` linework, pipes, CgPoints, and Locations to Blender geometry. It stores every source element, namespace, attribute, text value, and child order in indexed JSONL Blender Text datablocks referenced by the import collection. Civil coordinates map from `Northing, Easting, Elevation` to Blender `X = Easting`, `Y = Northing`, `Z = Elevation`.

## Requirements

- Blender 5.2 or later (Python 3.13). Blender 5.2.2 LTS is the tested version.
- The extension bundles Shapely 2.1.2 for boundary clipping and pyproj 3.7.2 for projected-coordinate conversion on Windows x64, Linux x64/arm64, and macOS x64/arm64. The projection wheels require glibc 2.28+ on Linux, macOS 13+ on Intel, or macOS 14+ on Apple Silicon.
- A valid LandXML 1.2 document; files with or without supported geometry are retained as structured records.
- PowerShell and a locally installed Blender executable when using the Windows install script.

## How-to: Civil 3D → Blender → Unreal with Cesium

This walkthrough takes a Civil 3D surface into Unreal, placed on the Cesium globe at its true location. It uses a real example: surface `FG-WDC1`, State Plane **NAD83 / Missouri East** (`EPSG:26996`), US survey feet, and a COGO point `1 - Building Corner` as the pivot.

**You need:** Blender 5.2+, Unreal Engine 5.x with **Cesium for Unreal** and the **Python Editor Script Plugin** enabled, and this repository's `scripts/` folder for the Unreal helpers.

### 1. Install the Blender extension

In Blender, open **Edit → Preferences → Extensions → ⌄ → Install from Disk** and choose the ZIP for your platform, for example `landxml_tin_importer-0.4.0-windows_x64.zip`. To build the ZIP yourself, see [Build and install](#build-and-install).

### 2. Export LandXML from Civil 3D

1. **Choose the pivot.** Create a COGO point at a known spot near the site, such as a building corner or survey control point. Give it a name and description, for example `1` / `Building Corner`. Use control with a published **WGS84 ellipsoid height** if you can (step 6 needs it).
2. **Export.** Use **Output → Export to LandXML** and include the **surface** and that **point**. Keep the drawing's real State Plane coordinates; don't move the drawing to 0,0 first.
3. **Note the coordinate system.** Write down the drawing's zone and datum (Civil 3D: **Settings → Drawing Settings → Units and Zone**). LandXML exports usually don't include it.

### 3. Import into Blender

1. Choose **File → Import → LandXML Data (.xml)** and pick the file.
2. Leave **Source Units** on **From LandXML (US Feet Fallback)**.
3. Enable **Use LandXML COGO Pivot** and choose `1 - Building Corner` from **Pivot COGO Point**. Check that the previewed Easting/Northing/Elevation matches Civil 3D.
4. In **US NAD83 Coordinate System**, type `Missouri East` and pick **NAD83 / Missouri East - EPSG:26996**, or type `26996`. The search also lists the NAD83(2011), NAD83(HARN) and NAD83(NSRS2007) versions of each zone (e.g. **NAD83(2011) / Missouri East - EPSG:6512**); pick the one that matches the drawing's coordinate system in Civil 3D (**Settings → Drawing Settings → Units and Zone**).
5. Set **Source Elevation Datum** (for example `NAVD88`). Fill in **Cesium Pivot Height (m)** only if you know the pivot's WGS84 ellipsoid height.
6. Click **Import**. The building corner is now at Blender `(0, 0, 0)` and the terrain is in meters. Invisible Civil 3D triangles are left out, so separate areas stay separate.

Edit materials as you like, but **don't move, rotate or scale** the imported surface. The exports check this and stop if anything has moved.

### 4. Export the Unreal package

1. With the surface selected, choose **File → Export → LandXML Unreal Package (.fbx + sidecars)**.
2. Optional cutout settings: a good start is **Edge Offset −1 m** and **Simplify 0.5 m**, which keeps the cutout just inside the TIN with fewer points. See [Edge offset and simplification](#edge-offset-and-simplification).
3. Save as, for example, `FG-WDC1.fbx`. You get three files side by side:

   | File | Purpose |
   |---|---|
   | `FG-WDC1.fbx` | Terrain mesh in meters, with the pivot at local zero |
   | `FG-WDC1.survey.json` | Pivot, Cesium longitude/latitude, grid convergence, file list |
   | `FG-WDC1_FG-WDC1.footprint.geojson` | Cesium cutout polygon |

   Keep the three files together; the Unreal helper finds them through the survey JSON.

### 5. Find the pivot's ellipsoid height

Cesium places things by **WGS84 ellipsoid height**, not survey elevation, and the importer won't guess the difference. To get it:

- **Best:** ask for the surveyor's GPS value for the control point. It's often listed as "ellipsoid height" or "h".
- **Otherwise:** convert the NAVD88 elevation in meters with [NGS GEOID18](https://geodesy.noaa.gov/GEOID/GEOID18/computation.html). Ellipsoid height = orthometric height + geoid height, and the geoid height is negative across the conterminous US.

  Example: NGS gives a geoid height of **−31.81 m** at the FG-WDC1 building corner. 866 US ft = 263.96 m NAVD88, so 263.96 − 31.81 = **232.15 m**.

  GEOID18 heights are relative to the NAD83(2011) ellipsoid. The WGS84 ellipsoid height differs by about a meter, which is usually fine for visualization; use survey-grade WGS84 control when it matters.

### 6. Place it in Unreal

1. Open a level with a **CesiumGeoreference** and a terrain tileset, such as Cesium World Terrain. Select the **CesiumGeoreference** actor in the Outliner.
2. Open **Window → Output Log**, switch the input box from **Cmd** to **Python**, and run (adjust the paths and height):

   ```python
   import sys; sys.path.append(r"D:\dev\LandXMLBlenderImporter\scripts")
   from import_landxml_unreal import import_package
   import_package(r"C:\Exports\FG-WDC1.survey.json", ellipsoid_height_meters=232.15)
   ```

   The helper:
   - imports the mesh into `/Game/LandXML`
   - anchors it with a **Cesium Globe Anchor** at the building corner
   - rotates it from grid north to true north (−0.43° for this site)
   - creates the cutout polygon actors

### 7. Cut the terrain under the mesh

1. Select the terrain tileset and click **Add Component → Cesium Polygon Raster Overlay**.
2. In its **Polygons** array, add **every** `..._Clip_####` actor the helper created.
3. Check that the tileset material supports clipping (the default Cesium material does), then press **Refresh Tileset**. The Cesium terrain under your surface disappears.

### 8. Verify and save

- **Check placement.** Fly to the building corner or another known point and compare against imagery or survey control.
  - Too high or too low: correct the ellipsoid height.
  - Rotated: confirm you used the right zone and datum.
- **Save.** The helper doesn't save the level for you.

### Common issues

| Symptom | Fix |
|---|---|
| Extra triangles join separate areas | Re-import; invisible Civil 3D faces are now excluded |
| "Pivot ellipsoid height is unknown" | Pass `ellipsoid_height_meters=` (step 5) |
| Mesh floats above or sinks below Cesium terrain | Height is wrong; NAVD88 elevation was probably used directly |
| Mesh is off by kilometers | Wrong State Plane zone or datum in step 3 |
| Export says objects are transformed | Clear the surface's location/rotation/scale, or re-import |
| Cutout misses the edges or leaves a gap | Re-export with a small negative **Edge Offset** |
| No footprint files were written | No coordinate system was set; use **CRS Override** in the export dialog |

The rest of this README covers each step in detail.

## Project layout

```text
landxml_importer/
  blender_manifest.toml  Blender extension metadata
  __init__.py            Blender operator and menu registration
  landxml.py             Blender-independent parser and coordinate conversion
  georef.py              Blender-independent GeoTIFF / world-file georeferencing
  survey.py              Survey pivot sidecars and projected CRS to WGS84 anchors
  footprint.py           Exact visible-TIN footprint GeoJSON and Cesium pieces
  blender_import.py      Mesh/curve creation, structured metadata, orthophoto UVs
  wheels/                Shapely wheels, fetched by scripts/fetch_wheels.py (not committed)
scripts/
  fetch_wheels.py        Download and verify the manifest's wheels from PyPI
  install_extension.ps1  Windows: fetch, validate, build, install, and enable
  install_extension.py   Blender-side install step used by the PowerShell script
  blender_smoke_test.py  Headless install-and-import check used by CI
  import_cesium_polygons.py  Unreal Editor helper for footprint polygon actors
  import_landxml_unreal.py   Unreal Editor helper that imports and globe-anchors a package
tests/
  fixtures/              Small, reviewable LandXML samples (trimmed_surface.xml drives the Blender smoke test)
  fixtures/landxml-1.2.xsd  Pinned official XSD for coverage checks
  test_landxml.py        Parser and conversion tests runnable without Blender
  test_landxml_schema.py XSD-backed metadata/adapter coverage
  test_georef.py         Georeferencing and UV-mapping tests runnable without Blender
```

The XML/domain and georeferencing code stays independent of `bpy`, while the operators remain thin and Blender-specific.

## Import behavior

- Preserves original `<P>` and `<F>` records and IDs in the structured metadata Text datablock.
- Excludes triangles marked invisible (`<F i="1">`) from the Blender mesh while preserving source records. Reports their count separately as `landxml_invisible_face_count`; they are not malformed/skipped faces. Re-import older meshes to apply this correction.
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
3. Leave **Source Units** set to **From LandXML (US Feet Fallback)** to use declared units. Generic `foot` and missing unit declarations warn and default to US survey feet (exactly 1200/3937 meters); declared meters and international feet are not overridden.
4. Keep **Shift Near Origin** enabled unless source-coordinate placement near Blender's global origin is required.
5. Enable **Use Survey Pivot** to enter a known source-coordinate Easting, Northing, and Elevation. Mesh vertices are located relative to this pivot while the exact source coordinates remain in custom properties.
   Alternatively, enable **Use LandXML COGO Pivot**, then search/select a named point from the selected file (for example `1 - Building Corner`). Its exact source Easting, Northing and Elevation are previewed and become the shared origin, overriding automatic shifting and manual pivot values. Nothing is selected automatically, even for a single point. Missing or duplicate point names stop the import rather than falling back to another origin. Changing the file or Point Order refreshes the candidates; reselect if the saved choice is no longer valid.
6. Keep **Validate Imported Geometry** enabled to cancel the complete import if Blender's mesh differs from the planned clipped output.
7. Use **Northing, Easting, Elevation** point order for standard LandXML 1.2 files. Try **Easting, Northing, Elevation** only when an imported terrain is mirrored or rotated.
8. Review the validation popup for source/output face counts, clipped source faces, linework objects, units, and skipped or degenerate faces.
9. In **US NAD83 Coordinate System**, type a zone name (for example `Colorado Central`) or EPSG number to search and select a suggestion. You can also type a code directly, such as `EPSG:2232`, including codes for other datums. Enter **Source Elevation Datum** separately. Leave the CRS field blank if unknown: the pivot is preserved, but no geographic anchor is invented.

The import creates a `LandXML_<filename>` collection plus a `LandXML_<filename>_metadata.json` index Text datablock and bounded JSONL record chunks. Each record stores its source node ID, parent ID, sibling order, name, namespace, attributes, text, and mixed-content tail. Mesh, curve, and point-cloud objects link to the index. Rebuild the full source tree by joining records through their parent and child indices.

## Supported input and limitations

- Tested with a Civil 3D 2027 LandXML export and standard LandXML 1.2 `Northing Easting Elevation` point order.
- Source units cover all eight LandXML 1.2 metric and imperial linear-unit values; generic feet default to US survey feet with an override warning. International feet are also available as an explicit override. All imported geometry is converted to meters.
- TIN faces must contain exactly three point IDs. Non-triangular records are skipped rather than truncated, and their reason is recorded in `landxml_skipped_face_reasons`.
- Faces with unresolved point IDs are skipped; their count and reason are also recorded in `landxml_skipped_face_reasons`.
- Zero-area, repeated-vertex, and collinear source triangles are retained without modification and counted in `landxml_degenerate_face_count`.
- All LandXML records are retained in structured metadata. Dedicated geometry adapters cover TIN surfaces, boundaries, breaklines, CgPoints, Locations, pipes, profiles, cross-sections, PlanFeatures, and `CoordGeom` lines/circular curves; other standard entities remain available as structured records but do not yet have specialized Blender geometry adapters.
- Automatic coordinate reference system discovery and mesh reprojection are not performed. A user-specified projected EPSG code converts the pivot to WGS84 longitude/latitude; source coordinate-system records are retained in metadata.
- Circular `CoordGeom` arcs are sampled at five-degree maximum angular intervals for Blender curve geometry; source arc parameters remain in metadata.

## TIN integrity

LandXML points/faces remain the source records. When an edge-trim boundary is active, the working mesh is clipped and retriangulated only where needed; generated vertex elevations are interpolated from their source triangle. Source face records remain in structured metadata, while the mesh fingerprint covers the resulting Blender geometry. A strict import is atomic: if parsing or output-geometry validation fails, created objects and the collection are removed rather than leaving a partial result.

Use **Object → Validate LandXML TIN Integrity** to compare the selected object's raw mesh coordinates and polygon loops against the stored import fingerprint. This intentionally ignores transforms and modifier output; it detects changes to the base mesh data itself. Object transforms are locked after import, but Blender Edit Mode, modifiers, and Python scripts can still alter a mesh. The validator identifies that divergence; it cannot prevent it.

To recover a source coordinate from a local mesh vertex, divide its Blender coordinate by `landxml_unit_to_meters` and add `landxml_origin_easting`, `landxml_origin_northing`, and `landxml_origin_elevation` respectively. Pivot values use the selected source-unit system.

## Civil 3D State Plane to Unreal / Cesium

The Civil 3D workflow offers an editable **US NAD83 Coordinate System** search field and defaults to US survey feet when the LandXML units are ambiguous or absent. Suggestions list non-deprecated NAD83, NAD83(2011), NAD83(HARN) and NAD83(NSRS2007) projected CRSs with Easting/Northing axes whose EPSG area of use includes the US, including State Plane, UTM and regional systems. Search by zone name, unit variant, realization (e.g. `2011`) or EPSG code; each zone's original NAD83 entry is listed first. The realizations are distinct datums, so choose the one the Civil 3D drawing uses; they differ by up to about a meter. Other datums can still be entered by EPSG code. Partial names must be completed by selecting a suggestion; ambiguous text is rejected. There is deliberately no default zone: State Plane requires the correct zone **and datum**. Export Civil 3D LandXML in the project's original survey coordinates; do not subtract a second origin in Civil 3D.

1. Enable **Use Survey Pivot** and enter a known Easting, Northing and Elevation in the resolved source units. These text fields retain double precision rather than rounding large survey coordinates through Blender float properties. Python operator callers must now pass pivot values as strings.
   Or use **Use LandXML COGO Pivot** to choose an exported survey/control point without copying coordinates. All georeferenced geometry, including the selected point, uses the same XYZ offset; the selected point lands at local zero. Its name/description is retained as `pivot_point` in the survey-reference JSON. Elevation-less COGO records follow the parser's existing zero-elevation convention; verify the preview before choosing a 3D pivot. Python operator callers use `use_cogo_pivot=True, pivot_point="1"`; the core importer accepts `pivot_point_name="1"`.
2. Select **NAD83 / Colorado Central (ftUS) - EPSG:2232**, for example, from **US NAD83 Coordinate System**, or type `2232` / `EPSG:2232` into the same field. Python callers can still use `coordinate_system="CUSTOM"` with `horizontal_epsg` for compatibility; a nonempty coordinate-system entry takes precedence. Codes are validated as projected Easting/Northing CRSs, and the pivot must be inside the CRS area of use. CRS selection does not override source geometry units; those still come from LandXML or the explicit Source Units override.
3. Enter **Source Elevation Datum**, for example `NAVD88`. If independently known, enter **Cesium Pivot Height (m)**: the pivot's **WGS84 ellipsoid height in meters**, not its State Plane/survey elevation. A horizontal CRS conversion does not convert NAVD88 to ellipsoid height.
4. With an imported object active, choose **File → Export → LandXML Survey Reference (.json)** (also in the Object menu). Save alongside the mesh export. The sidecar includes the exact source pivot, unit scale, CRS, datum, grid axes, WGS84 longitude/latitude, projection convergence/scale and warnings. Unknown ellipsoid height is JSON `null`, never zero or an assumed conversion.
5. Export the mesh with its existing local-zero origin and without recentering geometry. All georeferenced objects in the import share the same pivot; profiles and cross-sections are local station diagrams and are excluded from the sidecar. Transformed objects cause sidecar export to fail rather than describing stale placement.
6. In Unreal/Cesium, use the geographic anchor for placement and preserve the local mesh pivot. The JSON is a portable reference, **not an automatic Cesium importer**. Account for the mesh export's axis conversion and meters-to-centimeters conversion (Unreal), and verify orientation/scale against survey control. Do not apply a second unit conversion if the mesh importer already handled it.

Example control point for EPSG:2232: Easting `3000000`, Northing `1698067.4612223296`, Elevation `5000` US survey feet maps horizontally to approximately longitude `-105.5`, latitude `39.75`. A vertex ten survey feet east becomes local X `3.048006096` meters. The survey elevation remains separate from any supplied Cesium ellipsoid height.

Local mesh X/Y are **projected grid east/north**, not true east/north. The sidecar records meridian convergence and projection scales at the pivot, but does not rotate, warp, or reproject the mesh. An anchor alone cannot give exact globe placement across a large site or account for a Civil 3D ground-coordinate calibration. Horizontal datum accuracy depends on locally available PROJ operations/grids; no ballpark transformation is permitted, and missing required grids produce an explicit error. Verify placement against known WGS84 control. The reference is stored on the Blender import collection and georeferenced objects, so it survives saving/reopening the `.blend`.

### One-click Unreal package

With an imported object active, choose **File → Export → LandXML Unreal Package (.fbx + sidecars)** (also in the Object menu). Saving `site.fbx` writes:

- `site.fbx` — the import's TIN surfaces only, in meters with the survey pivot at local zero, modifiers applied and textures embedded. Unreal's FBX importer scales 1 m to 100 uu and maps Blender +Y (grid north) to Unreal −Y, which matches Cesium's east/south/up georeference frame (confirmed with UE 5.6 on a real export).
- `site.survey.json` — the survey reference above, plus a `package` block listing the FBX, mesh objects and footprint files.
- `site_<surface>.footprint.geojson` — one Cesium clipping footprint per surface (see below). Skipped with a warning when no CRS is known; use **CRS Override** to supply one.

**Selected Surfaces Only** limits the package to the selected surfaces of the active import. Scene **Unit Scale** must be 1.0, surfaces must be visible, and every check (transforms, modifiers, edited geometry, CRS) runs before any file is written, so a failed export leaves no partial package.

### Place the package in Unreal with Cesium

`scripts/import_landxml_unreal.py` imports the package FBX and places each surface on the globe in one step:

1. Enable **Cesium for Unreal** and **Python Editor Script Plugin**, and select the level's **CesiumGeoreference** actor.
2. In Unreal's Python console (adjust both paths; keep `scripts/` intact, as the helper imports `import_cesium_polygons.py` beside it):

   ```python
   import sys; sys.path.append(r"D:\dev\LandXMLBlenderImporter\scripts")
   from import_landxml_unreal import import_package
   actors = import_package(r"C:\path\to\site.survey.json", ellipsoid_height_meters=200.0)
   ```

3. Add the created footprint polygon actors to the tileset's **CesiumPolygonRasterOverlay** (see below), verify against survey control, and save the level.

For each surface the helper imports a static mesh into `/Game/LandXML` (`destination=` to change; re-running replaces the assets) with **complex-as-simple collision** on the TIN triangles. It spawns an actor, adds a **CesiumGlobeAnchorComponent**, moves it to the pivot's longitude/latitude, and yaws it by the recorded **meridian convergence**. That yaw turns grid north to its true direction on the globe. Without it, Missouri East's −0.43° convergence would shift a point 500 m from the pivot by about 3.7 m. Pass `apply_grid_convergence=False` only if you rotate elsewhere. The helper creates the footprint polygons at the same height; use `import_footprints=False` to skip them. The projection scale factor (about 0.99998 for Missouri East, 1 cm over 500 m) is not applied.

`ellipsoid_height_meters` is the **WGS84 ellipsoid height of the pivot** (the mesh's local zero). It is required unless the survey JSON already records it. Survey elevation (e.g. NAVD88 feet) is never substituted: in the conterminous US the ellipsoid height is roughly the orthometric height **minus ~30 m** (geoid separation), so get it from survey control or NGS tools. Everything is validated before any asset is imported. If placement fails, the actors created by that attempt are removed; imported assets remain for the next attempt.

## Export a Cesium clipping polygon

Select an imported TIN and choose **File → Export → Cesium Surface Footprint (.geojson)** (also in the Object menu). Uses the import CRS, or an optional searchable **CRS Override** when the original import had no CRS. For original NAD83 / Missouri East use `EPSG:26996`; XML US survey feet are converted to the CRS's meters automatically.

The exporter unions the raw visible mesh triangles in XY, without a convex hull or filling holes, and by default without simplification (see **Edge offset and simplification** below). Invisible LandXML faces are already excluded. Each disconnected island becomes a GeoJSON Polygon with its interior rings retained. Transformed objects, modifiers, edited base geometry and unspecified CRSs are rejected. Re-import older meshes before exporting. Mesh coordinates use Blender's stored precision; the footprint is topologically exact to that mesh, not a reconstruction of extra source-coordinate precision. Degenerate triangles with no XY area cannot define a polygon; their exclusion count is recorded.

Cesium Cartographic Polygon actors have **one ring each**. The GeoJSON includes a `cesium_unreal.pieces` extension: islands without holes use one actor, while islands with holes are exactly partitioned into hole-free triangles. Interior rings must **not** be imported as separate clipping actors, which would hide the holes rather than preserve them. Complex footprints with holes may produce many actors; the exporter reports the count.

### Edge offset and simplification

Both footprint export and the Unreal package offer two optional settings (default 0, the exact TIN edge):

- **Edge Offset (m)** shrinks (negative) or grows (positive) the cutout using mitred corners. An exact-edge cutout can show thin see-through slivers where the TIN edge and clipped terrain don't line up. A small **negative** offset keeps Cesium terrain under the TIN edge, so the TIN overlaps it instead of leaving a gap. A positive offset hides terrain that pokes through just outside the TIN, but it can open a visible hole beyond the edge.
- **Simplify (m)** drops boundary vertices that deviate less than the tolerance (topology-preserving Douglas–Peucker). Simplification then keeps every boundary point within the tolerance of the offset edge. With an inward offset at least as large as the tolerance, the cutout stays entirely inside the TIN; the exporter checks this.

The output records `exact_area_square_meters`, `area_square_meters`, `boundary_vertex_count` and the settings used. It warns when the boundary is no longer exact, or when an offset changed the island count, for example by splitting a narrow neck or removing a small island. On FG-WDC1 (3,102 exact boundary vertices), **Simplify 0.25** gives 725 vertices. **Offset −1, Simplify 0.5** gives 501 vertices fully inside the TIN; a narrow neck splits it into two islands.

To create the actors:

1. Enable **Cesium for Unreal** and **Python Editor Script Plugin** in Unreal.
2. Select the intended **CesiumGeoreference** actor in your level.
3. In Unreal's Python console, load the helper from this repository and import the export (adjust both paths):

   ```python
   exec(open(r"D:\dev\LandXMLBlenderImporter\scripts\import_cesium_polygons.py", encoding="utf-8").read())
   polygons = import_footprint(r"C:\path\to\FG-WDC1_footprint.geojson")
   ```

4. Add a **CesiumPolygonRasterOverlay** to the target tileset and add **all created actors** to its **Polygons** array. Keep their pieces together on the same overlay to preserve holes. Refresh the tileset and save your level.

`import_footprint(..., height_meters=250)` optionally places the spline near terrain for editing. This is only a polygon display height (ellipsoid meters), **not** a vertical-datum conversion or the height of your imported mesh. Clipping is 2.5D and visual: hidden tileset geometry can still have collision. The helper does not change materials, overlay settings, existing actors, or save the level automatically. Imports can be undone; failed imports remove actors created during that attempt.

Coordinates are longitude/latitude degrees, with every perimeter vertex transformed from the projected CRS; straight geographic edges connect those vertices. Very long edges or antimeridian-crossing footprints require additional handling (antimeridian crossings are rejected). No survey-grade accuracy beyond the underlying datum transformation is implied. See [Cesium's polygon clipping guide](https://cesium.com/learn/unreal/unreal-clipping/) for overlay and material setup.

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
python -m pip install shapely==2.1.2 pyproj==3.7.2
python -m unittest discover -s tests -v
```

## Build and install

The Shapely, pyproj and certifi wheels are not committed; they are downloaded from PyPI and SHA-256 verified against the list in `blender_manifest.toml`.

One command fetches the wheels, rebuilds the extension, and installs/enables it in Blender on Windows:

```powershell
pwsh scripts/install_extension.ps1
```

The script checks the standard Blender Foundation installation at `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` first and then the Microsoft Store execution alias. Add another path to `blenderCandidates` in [scripts/install_extension.ps1](scripts/install_extension.ps1) when Blender is installed elsewhere. **Restart Blender** (or disable/re-enable the extension in Preferences) afterward; Blender will not hot-reload an already-enabled extension's code.

To do it manually instead:

```powershell
python scripts/fetch_wheels.py
blender --command extension validate landxml_importer
blender --command extension build --source-dir landxml_importer --split-platforms
```

The build writes one ZIP per platform (for example `landxml_tin_importer-0.4.0-windows_x64.zip`), each containing only that platform's Shapely and pyproj wheels. Install the ZIP for your platform through Blender's **Preferences → Extensions → Install from Disk**. Either way, the command appears under **File → Import → LandXML Data (.xml)**.

To smoke-test a built ZIP in an isolated Blender profile (install, boundary-trimmed import, integrity check, orthophoto):

```powershell
$env:BLENDER_USER_RESOURCES = "$env:TEMP\landxml-smoke"
blender -b --factory-startup --python-exit-code 1 --python scripts/blender_smoke_test.py -- landxml_tin_importer-0.4.0-windows_x64.zip
```

## Continuous integration and releases

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every push:

1. Unit tests on Python 3.13 (Blender 5.2's bundled version).
2. On Linux with Blender 5.2.2: fetch wheels, validate, build all platform ZIPs, and run the smoke test against the `linux_x64` ZIP. The ZIPs are uploaded as the `extension-zips` artifact.
3. On a `v*` tag: check that the tag matches the manifest version, then publish a GitHub release with all ZIPs and that version's `CHANGELOG.md` section as notes.

Release checklist:

1. Bump `version` in `blender_manifest.toml` and add a dated `## <version> - YYYY-MM-DD` section to `CHANGELOG.md`.
2. Merge to `master` once CI passes.
3. Tag and push: `git tag v<version>` then `git push origin v<version>`.
4. Upload the ZIPs from the release to the Blender Extensions platform.

## Support

Use [GitHub Issues](https://github.com/jonathanmcmichael/LandXMLBlenderImporter/issues) for reproducible bugs and compatibility reports. Do not attach confidential project LandXML files; use a minimal sanitized sample when one is needed to reproduce an issue.

## License

This project is licensed under the GNU General Public License v3.0 or later. See `LICENSE`.

## Design boundaries

The default point order is `Northing Easting Elevation` per the LandXML 1.2 standard, but this is exposed as an import option (`Point Order`) since some real-world exports reverse it. Automatic coordinate-system discovery, vertical-datum conversion, and whole-mesh reprojection remain out of scope.

Long, thin ("sliver") triangles from the source TIN are left as-is rather than remeshed. They can represent dense point layout along linear features such as curbs, centerlines, and swales. Fixing them would require lossy simplification or full retriangulation, both of which conflict with exact point and face preservation.

## Verified against a real export

Validated against a real Civil 3D 2027 export (single TIN surface, 55k points, 110k faces, declared US Survey Feet, no `<CoordinateSystem>`): parses in well under a second, unit conversion matches the file's own `elevMax`/`elevMin` metadata exactly, and the imported mesh renders as a coherent, correctly oriented finished-grade surface with zero invalid faces. Multi-surface shared-origin alignment is currently only exercised by the synthetic `tests/fixtures/two_surfaces.xml` fixture — a real multi-surface export hasn't been tested yet.
