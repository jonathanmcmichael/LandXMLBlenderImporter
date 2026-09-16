# Blender Extensions listing draft

## Name

LandXML TIN Importer

## Tagline

Import authoritative LandXML TIN surfaces

## Summary

Import Civil 3D LandXML terrain surfaces directly into Blender while preserving the source point-and-face triangulation.

## Description

LandXML TIN Importer creates Blender meshes from the authoritative `<P>` points and `<F>` faces in LandXML terrain exports. It does not regenerate or simplify the source triangulation.

The importer maps civil Northing, Easting, and Elevation coordinates to Blender axes, supports meters and both common foot definitions, and can shift large horizontal coordinates near the Blender origin to avoid precision problems. The original geospatial origin and import details remain available as object custom properties.

Multiple surfaces from one file share the same local origin and remain aligned. Each import is placed in its own Blender collection.

## Primary workflow

1. In Civil 3D, export the surface to LandXML with **Points and Faces** included.
2. In Blender, choose **File → Import → LandXML TIN Surface (.xml)**.
3. Select the source units and point order.
4. Keep **Shift Near Origin** enabled for large civil coordinates.

## Support

Bug reports and compatibility issues: https://github.com/jonathanmcmichael/LandXMLBlenderImporter/issues

Do not attach confidential project LandXML files. Create a minimal sanitized reproduction when sample data is necessary.

## Source

https://github.com/jonathanmcmichael/LandXMLBlenderImporter
