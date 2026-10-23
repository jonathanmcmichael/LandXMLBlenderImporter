# Blender Extensions listing draft

## Name

LandXML Importer

## Tagline

Import LandXML terrain and civil linework

## Summary

Import LandXML terrain and civil linework into Blender, with a structured record of every source XML element and attribute.

## Description

LandXML Importer creates Blender meshes from `<P>` points and `<F>` faces, applies edge-trim boundaries to the working TIN, and imports boundaries, breaklines, alignments, parcels, pipes, profiles, cross-sections, PlanFeatures, CgPoints, Locations, and structures as separate native curves or point-cloud meshes where their geometry is recognized. Every source element and attribute remains in indexed JSONL Text datablocks linked to the import collection; other schema entities remain structured there.

The importer maps civil Northing, Easting, and Elevation coordinates to Blender axes, reads declared linear units with overrides for ambiguity, and can shift large horizontal coordinates near the Blender origin. Source and output face counts, units, object categories, and geospatial origins are retained in custom properties.

Multiple surfaces from one file share the same local origin and remain aligned. Each import is placed in its own Blender collection.

## Primary workflow

1. In Civil 3D, export the surface to LandXML with **Points and Faces** included.
2. In Blender, choose **File → Import → LandXML Data (.xml)**.
3. Leave units on automatic detection or select an explicit override; choose the point order.
4. Keep **Shift Near Origin** enabled for large civil coordinates.
5. Select an imported surface and choose **Object → Use Breaklines on Surface** to mark matching TIN edges sharp, as UV seams, or both.

## Support

Bug reports and compatibility issues: https://github.com/jonathanmcmichael/LandXMLBlenderImporter/issues

Do not attach confidential project LandXML files. Create a minimal sanitized reproduction when sample data is necessary.

## Source

https://github.com/jonathanmcmichael/LandXMLBlenderImporter
