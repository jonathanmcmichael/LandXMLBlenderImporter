# LandXML Importer Roadmap

## Purpose

This roadmap tracks a Blender 5.2+ importer that turns LandXML documents into
useful Blender geometry and structured metadata. The parser preserves all XML
elements, namespaces, attributes, text, and order; geometry adapters convert
recognized LandXML entities to meshes, curves, or point clouds.

The ordering intentionally protects source-data integrity before adding
convenience features or release automation.

## Principles

- Preserve source records in reconstructible Blender metadata; report source and output geometry separately.
- Apply edge-trim boundaries to working TINs without discarding source face records.
- Make unsupported or invalid source data visible rather than silently changing it.
- Keep XML parsing independent of Blender so it remains fast and testable.
- Route all importer entry points through one parser and conversion core.

## Current Parity Coverage

- [x] Pin LandXML 1.2 XSD and retain every source element, namespace, attribute, text value, mixed-content tail, and sibling order as indexed Blender JSONL Text data.
- [x] Convert surfaces with edge-trim outer/hide boundaries, boundaries, breaklines, PlanFeatures, generic `CoordGeom` lines/arcs/irregular lines, pipes/structures, profile alignments, cross-section surfaces, CgPoints, and Locations to native Blender geometry.
- [x] Add an Object-menu operation to mark existing mesh edges aligned with breaklines as sharp and/or UV seams, with a match report and no topology changes.
- [x] Resolve declared LandXML units with explicit overrides and warning for ambiguous generic feet.
- [x] Route every import through the extension's shared parser and conversion core; the legacy root `landxml_import.py` script has been removed.
- [x] Validate with schema-backed tests and Blender 5.2 import of the supplied Civil 3D 2027 export.
- [ ] Add specialized geometry adapters for remaining schema types such as roadway design/traffic records, survey observations, spirals, and volume geometry. These are currently preserved in structured metadata.
- [ ] Verify the per-platform Shapely wheels by installing each split build on macOS and Linux as well as Windows. CI now installs and exercises the host-compatible manifest wheels on x64 and arm64 runners for all three operating systems; mark complete after that matrix passes.

## Phase 1: Data Integrity and Parser Coverage

**Goal:** Make parser behavior explicit, safe, and protected by tests.

### Phase 1 Work

- [x] Pin the official LandXML 1.2 XSD and test that specialized adapters are schema-defined while unadapted elements/attributes remain in the generic record tree.
- [x] Define the handling of `<F>` elements with more than three point IDs in `landxml_importer/landxml.py`.
  - Preferred behavior: skip non-triangle faces, increment the skipped-face count, and retain a separate reason/count for unsupported face topology.
  - Do not silently truncate an n-gon to its first three IDs.
- [x] Ensure every point ID referenced by an accepted face exists, not only the first three IDs.
- [x] Add unit tests for duplicate point IDs, missing `<Definition>` wrappers, unnamed surfaces, malformed XML, and unsupported point order.
- [x] Add tests for non-triangle faces and invalid point references, asserting both geometry and diagnostic counts.
- [x] Add a large-coordinate fixture or direct test to verify shared-origin shifting preserves relative offsets without unexpected precision loss.
- [x] Add complete type annotations to private parser helpers where they clarify XML and domain boundaries; the parser helpers already have typed parameters and return contracts.

### Phase 1 Completion Criteria

- Unsupported topology and malformed records have deterministic, documented outcomes.
- The parser test suite covers normal imports plus each supported failure/skip path.
- `python -m unittest discover -s tests -v` passes.

## Phase 2: Import Diagnostics and User-Facing Errors

**Goal:** Let Blender users understand what was imported and why records were skipped.

### Phase 2 Work

- [x] Emit a concise diagnostic per imported surface from `landxml_importer/blender_import.py`: surface name, vertex count, face count, and skipped-face counts by reason.
- [x] Surface meaningful messages in the Blender operator for unreadable XML, no usable TIN surfaces, unsupported units, and unsupported point order.
- [x] Add a post-import summary to the operator report when one or more records were skipped.
- [x] Keep object custom properties as the durable source of origin, unit, and import statistics.
- [x] Document where users can find diagnostic output and what common messages mean.

### Phase 2 Completion Criteria

- A user can distinguish a complete import from an import with skipped geometry without inspecting Python code.
- Diagnostics identify the affected surface and count skipped records.
- A manual Blender import confirms the messages are readable and non-noisy.

## Phase 3: Documentation and Compatibility Evidence

**Goal:** Replace assumptions with reproducible compatibility information.

### Phase 3 Work

- [x] Add a concise supported-input section to `README.md`: tested LandXML version/exporter combinations, accepted units, point orders, and triangle-only expectation.
- [x] Add a limitations section explaining the chosen non-triangle behavior and intentional non-goals.
- [x] Add a sanitized real-world multi-surface LandXML fixture, or document why it cannot be published and record the manual validation procedure instead; no publishable real-world multi-surface export is currently available.
- [x] Verify the US survey foot conversion against an authoritative reference and add a short source comment next to the constant.
- [x] Add a short troubleshooting table for rotated/mirrored terrain, incorrect scale, missing surfaces, and skipped faces.

### Phase 3 Completion Criteria

- A civil/Blender user can select the correct settings and diagnose common failures from the README.
- Multi-surface behavior has either automated real-export coverage or a repeatable documented manual check.

## Phase 4: Packaging and Continuous Validation

**Goal:** Ensure every change remains installable as a Blender extension.

### Phase 4 Work

- [x] Add a CI workflow that runs the Blender-independent unit tests on supported Python versions.
- [x] Add an extension validation/build job using Blender's command-line extension tooling, plus a headless install-and-import smoke test.
- [x] Publish the supported Blender versions and CI matrix in the repository documentation.
- [x] Add a release checklist covering version updates, changelog entries, extension validation, ZIP creation, and a Blender smoke test.

### Phase 4 Completion Criteria

- Pull requests automatically run parser tests and extension packaging validation.
- A release can be reproduced from a documented checklist without relying on local memory.

## Phase 5: Repository Cleanup and Maintenance

**Goal:** Leave one clearly supported import path and a small, understandable codebase.

### Phase 5 Work

- [x] Confirm `landxml_import.py` is not needed for backwards compatibility or external users.
- [x] Delete it.
- [x] Keep the packaged extension limited to `landxml_importer/` and update project-layout documentation after cleanup.
- [x] Add lightweight contributor guidance: local test command, extension build command, and fixture expectations.

### Phase 5 Completion Criteria

- There is no ambiguous second importer implementation at the repository root.
- New contributors have one documented development and validation path.

## Suggested Delivery Sequence

1. [x] Complete Phase 1 parser coverage and integrity tests.
2. [x] Complete Phase 2 diagnostics and the Blender headless import smoke test.
3. [x] Complete Phase 3 compatibility documentation; record a manual multi-surface procedure until a publishable real-world sample is available.
4. [x] Add Phase 4 CI before the next feature release.
5. [x] Complete Phase 5 contributor guidance and repository cleanup.

## Deliberate Limits

- Retriangulation, decimation, or automatic sliver-triangle cleanup.
- Automatic coordinate reference system discovery or reprojection. Orthophoto draping requires the image to already share the LandXML's CRS and units.
- Vendor-specific extensions are retained as source records but are not guaranteed semantic geometry adapters.
- CAD-equivalent editability; outputs use Blender-native meshes, curves, and point clouds with LandXML semantics in metadata.
