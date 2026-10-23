# Changelog

All notable changes to this project are documented here.

## 0.3.0 - 2026-10-23

- Require Blender 5.2 or later (Python 3.13); drop the Python 3.11 wheels used by Blender 4.2–5.0.
- Ship one extension ZIP per platform, each bundling only its own Shapely wheel.
- Stop setting the deprecated `Material.use_nodes` when creating the orthophoto material.
- Add **Object → Apply Georeferenced Orthophoto** to drape a north-up GeoTIFF or world-file image onto imported surfaces by source coordinates, without modifying mesh geometry.
- Read GeoTIFF placement (tiepoint/pixel scale or transformation, PixelIsPoint, linear units) in pure Python, including BigTIFF.
- Reject geographic, Web Mercator, rotated, and unit-mismatched images, and warn when surface vertices fall outside the image.
- Fix `CoordGeom` `IrregularLine` segments being silently dropped.
- Fix the integrity validator reporting a mismatch on unmodified meshes; the fingerprint now reflects Blender's stored single-precision coordinates. Re-import surfaces imported by earlier builds to refresh their fingerprint.
- Clip each surface only by the boundaries nested inside it, so multi-surface files with per-surface boundaries import instead of failing.
- Report a clear error for a `Line` missing `Start`/`End`, and skip non-finite TIN point coordinates as missing points.
- Hash the source file in a streaming pass rather than loading it into memory a second time.

## 0.2.0 - 2026-09-22

- Add optional survey-coordinate E/N/Z pivot input while retaining local Blender geometry.
- Preserve source face winding and remove automatic normal flipping and smooth-shading changes.
- Reject non-triangular face records instead of truncating them, with structured skip diagnostics.
- Warn about retained zero-area source triangles without changing topology.
- Store source SHA-256 provenance and a raw ordered-geometry fingerprint on imported objects.
- Add an Object menu integrity validator and lock imported object transforms.
- Validate Blender's created vertex and face counts, rolling back the complete import if strict validation fails.

## 0.1.0 - 2026-09-16

- Import authoritative LandXML TIN points and faces without retriangulation.
- Map LandXML Northing/Easting/Elevation coordinates into Blender axes.
- Support meters, international feet, and US survey feet.
- Shift large horizontal civil coordinates near the Blender origin while retaining the source origin as object metadata.
- Preserve alignment across multiple surfaces with a shared per-file origin.
- Support configurable point order for non-standard exports.
- Group imported surfaces into a per-file Blender collection.
- Correct triangle orientation per face and apply angle-based smooth shading.
- Record source, unit, origin, vertex, face, and skipped-face metadata.
- Validate the extension and package with Blender 5.2.2 LTS.
- Verify a real Civil 3D 2027 TIN export containing approximately 55,000 points and 110,000 faces.
