# Changelog

All notable changes to this project are documented here.

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
