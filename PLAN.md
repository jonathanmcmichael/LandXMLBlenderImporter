# LandXML TIN Importer Roadmap

## Purpose

This roadmap builds on the `v0.1.0` baseline: a Blender 4.2+ extension
that imports authoritative LandXML TIN points and faces, preserves
multi-surface alignment, and handles common Civil 3D coordinate conventions.

The ordering intentionally protects source-data integrity before adding
convenience features or release automation.

## Principles

- Preserve the source `<P>` point data and `<F>` triangulation without retriangulating.
- Make unsupported or invalid source data visible rather than silently changing it.
- Keep XML parsing independent of Blender so it remains fast and testable.
- Keep scope focused on TIN surface import; breaklines, boundaries, and automatic coordinate-system discovery remain separate future decisions.

## Phase 1: Data Integrity and Parser Coverage

**Goal:** Make parser behavior explicit, safe, and protected by tests.

### Phase 1 Work

- [ ] Define the handling of `<F>` elements with more than three point IDs in `landxml_importer/landxml.py`.
  - Preferred behavior: skip non-triangle faces, increment the skipped-face count, and retain a separate reason/count for unsupported face topology.
  - Do not silently truncate an n-gon to its first three IDs.
- [ ] Ensure every point ID referenced by an accepted face exists, not only the first three IDs.
- [ ] Add unit tests for duplicate point IDs, missing `<Definition>` wrappers, unnamed surfaces, malformed XML, and unsupported point order.
- [ ] Add tests for non-triangle faces and invalid point references, asserting both geometry and diagnostic counts.
- [ ] Add a large-coordinate fixture or direct test to verify shared-origin shifting preserves relative offsets without unexpected precision loss.
- [ ] Add complete type annotations to private parser helpers where they clarify XML and domain boundaries.

### Phase 1 Completion Criteria

- Unsupported topology and malformed records have deterministic, documented outcomes.
- The parser test suite covers normal imports plus each supported failure/skip path.
- `python -m unittest discover -s tests -v` passes.

## Phase 2: Import Diagnostics and User-Facing Errors

**Goal:** Let Blender users understand what was imported and why records were skipped.

### Phase 2 Work

- [ ] Emit a concise diagnostic per imported surface from `landxml_importer/blender_import.py`: surface name, vertex count, face count, and skipped-face counts by reason.
- [ ] Surface meaningful messages in the Blender operator for unreadable XML, no usable TIN surfaces, unsupported units, and unsupported point order.
- [ ] Add a post-import summary to the operator report when one or more records were skipped.
- [ ] Keep object custom properties as the durable source of origin, unit, and import statistics.
- [ ] Document where users can find diagnostic output and what common messages mean.

### Phase 2 Completion Criteria

- A user can distinguish a complete import from an import with skipped geometry without inspecting Python code.
- Diagnostics identify the affected surface and count skipped records.
- A manual Blender import confirms the messages are readable and non-noisy.

## Phase 3: Documentation and Compatibility Evidence

**Goal:** Replace assumptions with reproducible compatibility information.

### Phase 3 Work

- [ ] Add a concise supported-input section to `README.md`: tested LandXML version/exporter combinations, accepted units, point orders, and triangle-only expectation.
- [ ] Add a limitations section explaining the chosen non-triangle behavior and intentional non-goals.
- [ ] Add a sanitized real-world multi-surface LandXML fixture, or document why it cannot be published and record the manual validation procedure instead.
- [ ] Verify the US survey foot conversion against an authoritative reference and add a short source comment next to the constant.
- [ ] Add a short troubleshooting table for rotated/mirrored terrain, incorrect scale, missing surfaces, and skipped faces.

### Phase 3 Completion Criteria

- A civil/Blender user can select the correct settings and diagnose common failures from the README.
- Multi-surface behavior has either automated real-export coverage or a repeatable documented manual check.

## Phase 4: Packaging and Continuous Validation

**Goal:** Ensure every change remains installable as a Blender extension.

### Phase 4 Work

- [ ] Add a CI workflow that runs the Blender-independent unit tests on supported Python versions.
- [ ] Add an extension validation/build job using Blender's command-line extension tooling.
- [ ] Publish the supported Blender versions and CI matrix in the repository documentation.
- [ ] Add a release checklist covering version updates, changelog entries, extension validation, ZIP creation, and a manual Blender smoke test.

### Phase 4 Completion Criteria

- Pull requests automatically run parser tests and extension packaging validation.
- A release can be reproduced from a documented checklist without relying on local memory.

## Phase 5: Repository Cleanup and Maintenance

**Goal:** Leave one clearly supported import path and a small, understandable codebase.

### Phase 5 Work

- [ ] Confirm `landxml_import.py` is not needed for backwards compatibility or external users.
- [ ] Delete it if unneeded, or move it to an explicitly labelled example/migration location with a deprecation note.
- [ ] Keep the packaged extension limited to `landxml_importer/` and update project-layout documentation after cleanup.
- [ ] Add lightweight contributor guidance: local test command, extension build command, and fixture expectations.

### Phase 5 Completion Criteria

- There is no ambiguous second importer implementation at the repository root.
- New contributors have one documented development and validation path.

## Suggested Delivery Sequence

1. Complete Phase 1 in a focused parser-and-tests pull request.
2. Complete Phase 2 with a Blender manual smoke test and README diagnostic notes.
3. Complete Phase 3 once a sanitizable multi-surface export is available.
4. Add Phase 4 CI before the next feature release.
5. Complete Phase 5 after confirming no users depend on the legacy script.

## Out of Scope for This Roadmap

- Retriangulation, decimation, or automatic sliver-triangle cleanup.
- Parsing breaklines and boundaries independently of the authoritative face list.
- Automatic coordinate reference system discovery or georeferencing transforms.
- General LandXML feature support beyond authoritative TIN surfaces.
