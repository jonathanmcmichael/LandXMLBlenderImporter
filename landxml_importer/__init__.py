"""LandXML TIN Importer Blender extension."""

from functools import lru_cache
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .blender_import import (
    apply_breaklines_to_surface,
    apply_orthophoto,
    export_survey_reference,
    export_cesium_footprint,
    export_unreal_package,
    import_landxml,
    object_geometry_fingerprint,
)
from .survey import parse_coordinate, resolve_crs_entry, search_us_nad83_crs
from .landxml import LandXMLError, cogo_pivot, read_cogo_points


@lru_cache(maxsize=1)
def _cached_cogo_points(filepath, point_order, modified, size):
    return read_cogo_points(filepath, point_order=point_order)


def _pivot_candidates(operator):
    path = Path(operator.filepath)
    if not operator.filepath or not path.is_file():
        raise LandXMLError("Select a LandXML file to list its COGO points")
    stat = path.stat()
    return _cached_cogo_points(str(path.resolve()), operator.point_order, stat.st_mtime_ns, stat.st_size)


def _cogo_label(point):
    attributes = dict(point.attributes)
    name = attributes.get("name", "")
    description = attributes.get("desc") or attributes.get("code")
    return f"{name} - {description}" if description else name


def _selected_cogo_name(operator):
    points = _pivot_candidates(operator)
    selection = operator.pivot_point.strip()
    labels = [point for point in points if _cogo_label(point) == selection]
    name = dict(labels[0].attributes).get("name", "") if len(labels) == 1 else selection
    cogo_pivot(points, name)
    return name


def _search_cogo_points(self, context, edit_text):
    try:
        points = _pivot_candidates(self)
    except (OSError, ValueError) as exc:
        self.report({"ERROR"}, str(exc))
        return []
    tokens = edit_text.casefold().split()
    return [
        (_cogo_label(point), f"E/N/Z: {point.coordinate}")
        for point in points
        if dict(point.attributes).get("name")
        and all(token in _cogo_label(point).casefold() for token in tokens)
    ]


def _search_coordinate_system(self, context, edit_text):
    return search_us_nad83_crs(edit_text)


def _footprint_offset_property():
    return FloatProperty(
        name="Edge Offset (m)",
        description=(
            "Shrink (negative) or grow (positive) the cutout from the exact TIN edge. "
            "Negative keeps Cesium terrain under the TIN edge so no see-through gap appears"
        ),
        default=0.0, soft_min=-10.0, soft_max=10.0, step=10, precision=2,
    )


def _footprint_simplify_property():
    return FloatProperty(
        name="Simplify (m)",
        description=(
            "Drop boundary vertices that deviate less than this from the edge. "
            "Use an inward offset at least this large to stay inside the TIN"
        ),
        default=0.0, min=0.0, soft_max=5.0, step=10, precision=2,
    )


class IMPORT_SCENE_OT_landxml_tin(Operator, ImportHelper):
    bl_idname = "import_scene.landxml_tin"
    bl_label = "Import LandXML Data"
    bl_description = "Import LandXML surfaces, boundaries, breaklines, features, and point records"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".xml"
    filter_glob: StringProperty(default="*.xml;*.landxml", options={"HIDDEN"})

    source_units: EnumProperty(
        name="Source Units",
        description="Use the file declaration when available; override ambiguous or missing units",
        items=(
            ("AUTO", "From LandXML (US Feet Fallback)", "Use declared units; missing units or generic feet default to US survey feet with a warning"),
            ("MILLIMETERS", "Millimeters", "One source unit equals 0.001 meters"),
            ("CENTIMETERS", "Centimeters", "One source unit equals 0.01 meters"),
            ("METERS", "Meters", "Source coordinates are meters"),
            ("KILOMETERS", "Kilometers", "One source unit equals 1000 meters"),
            ("INCHES", "Inches", "One source unit equals exactly 0.0254 meters"),
            ("INTERNATIONAL_FEET", "International Feet", "One foot equals exactly 0.3048 meters"),
            ("US_SURVEY_FEET", "US Survey Feet", "One foot equals 1200/3937 meters"),
            ("MILES", "Miles", "One mile equals 1609.344 meters"),
            ("US_SURVEY_MILES", "US Survey Miles", "One mile equals 5280 US survey feet"),
        ),
        default="AUTO",
    )
    shift_to_origin: BoolProperty(
        name="Shift Near Origin",
        description="Subtract one shared minimum Easting/Northing while retaining source elevation",
        default=True,
    )
    use_custom_pivot: BoolProperty(
        name="Use Survey Pivot",
        description="Use the supplied source Easting, Northing, and Elevation as the local mesh origin",
        default=False,
    )
    use_cogo_pivot: BoolProperty(
        name="Use LandXML COGO Pivot",
        description="Choose a named COGO point from this file as the shared source-coordinate origin",
        default=False,
    )
    pivot_point: StringProperty(
        name="Pivot COGO Point",
        description="Search point name or description; select a suggestion or enter an exact point name",
        search=_search_cogo_points,
        search_options={"SUGGESTION"},
    )
    pivot_easting: StringProperty(name="Pivot Easting", default="0")
    pivot_northing: StringProperty(name="Pivot Northing", default="0")
    pivot_elevation: StringProperty(name="Pivot Elevation", default="0")
    coordinate_system: StringProperty(
        name="US NAD83 Coordinate System",
        description="Type a zone name to search, or enter an EPSG code directly; blank leaves the CRS unspecified",
        search=_search_coordinate_system,
        search_options={"SUGGESTION"},
        default="",
    )
    horizontal_epsg: StringProperty(
        name="Manual Projected EPSG",
        description="Projected CRS code including zone and datum, e.g. 2232; blank preserves pivot without conversion",
        default="",
    )
    vertical_datum: StringProperty(
        name="Source Elevation Datum",
        description="Survey elevation datum, e.g. NAVD88; blank means unknown",
        default="",
    )
    ellipsoid_height: StringProperty(
        name="Cesium Pivot Height (m)",
        description="Known WGS84 ellipsoid height of the pivot in meters, NOT survey elevation; blank means unknown",
        default="",
    )
    validate_original_faces: BoolProperty(
        name="Validate Imported Geometry",
        description="Cancel the import if Blender does not retain the planned mesh vertex and face counts",
        default=True,
    )
    point_order: EnumProperty(
        name="Point Order",
        description="Coordinate order used by the LandXML <P> point values",
        items=(
            ("NEZ", "Northing, Easting, Elevation", "LandXML 1.2 standard order; most Civil 3D exports"),
            ("ENZ", "Easting, Northing, Elevation", "Non-standard order; use if the terrain appears mirrored or rotated"),
        ),
        default="NEZ",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "source_units")
        layout.prop(self, "point_order")
        layout.label(text="Civil 3D: State Plane / US survey feet")
        layout.prop(self, "coordinate_system")
        if self.coordinate_system == "CUSTOM":
            layout.prop(self, "horizontal_epsg")
        layout.prop(self, "vertical_datum")
        layout.prop(self, "ellipsoid_height")
        layout.prop(self, "use_cogo_pivot")
        if self.use_cogo_pivot:
            layout.prop(self, "pivot_point")
            try:
                points = _pivot_candidates(self)
                if not any(dict(point.attributes).get("name") for point in points):
                    layout.label(text="No named COGO points in this file", icon="ERROR")
                elif self.pivot_point:
                    point = cogo_pivot(points, _selected_cogo_name(self))
                    for label, value in zip(("Easting", "Northing", "Elevation"), point.coordinate):
                        layout.label(text=f"{label}: {value:.12f}")
            except (OSError, ValueError) as exc:
                layout.label(text=str(exc), icon="ERROR")
        else:
            layout.prop(self, "shift_to_origin")
            layout.prop(self, "use_custom_pivot")
            if self.use_custom_pivot:
                layout.prop(self, "pivot_easting")
                layout.prop(self, "pivot_northing")
                layout.prop(self, "pivot_elevation")
        layout.prop(self, "validate_original_faces")

    def execute(self, context):
        for obj in context.selected_objects:
            obj.select_set(False)
        try:
            horizontal_epsg = resolve_crs_entry(self.coordinate_system, self.horizontal_epsg)
            result = import_landxml(
                self.filepath,
                source_units=self.source_units,
                shift_to_origin=self.shift_to_origin,
                point_order=self.point_order,
                custom_origin=(
                    parse_coordinate(self.pivot_easting),
                    parse_coordinate(self.pivot_northing),
                    parse_coordinate(self.pivot_elevation),
                )
                if self.use_custom_pivot and not self.use_cogo_pivot
                else None,
                pivot_point_name=_selected_cogo_name(self) if self.use_cogo_pivot else "",
                validate_original_faces=self.validate_original_faces,
                horizontal_epsg=horizontal_epsg,
                vertical_datum=self.vertical_datum,
                ellipsoid_height=self.ellipsoid_height,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        imported = result.surfaces
        skipped = sum(obj["landxml_skipped_face_count"] for obj in imported)
        degenerate = sum(obj["landxml_degenerate_face_count"] for obj in imported)
        source_faces = sum(obj["landxml_source_face_count"] for obj in imported)
        clipped_faces = sum(obj["landxml_boundary_clipped_face_count"] for obj in imported)
        point_count = sum(obj["landxml_point_count"] for obj in result.point_clouds)
        bpy.ops.wm.landxml_import_validation(
            "INVOKE_DEFAULT",
            source_name=bpy.path.display_name_from_filepath(self.filepath),
            surface_count=len(imported),
            vertex_count=sum(obj["landxml_vertex_count"] for obj in imported),
            face_count=sum(obj["landxml_face_count"] for obj in imported),
            source_face_count=source_faces,
            invisible_face_count=sum(obj["landxml_invisible_face_count"] for obj in imported),
            clipped_face_count=clipped_faces,
            curve_count=len(result.curves),
            point_count=point_count,
            source_units=result.source_units,
            skipped_face_count=skipped,
            degenerate_face_count=degenerate,
            validation_enabled=self.validate_original_faces,
        )
        if result.unit_warning:
            self.report({"WARNING"}, result.unit_warning)
        if not horizontal_epsg.strip():
            self.report({"WARNING"}, "No projected CRS supplied; pivot preserved without Cesium longitude/latitude")
        elif not self.ellipsoid_height.strip():
            self.report({"WARNING"}, "Cesium longitude/latitude available; ellipsoid height still unknown")
        if skipped or degenerate:
            self.report(
                {"WARNING"},
                f"Imported {len(imported)} surface(s); skipped {skipped} malformed face(s), retained {degenerate} degenerate face(s).",
            )
        else:
            self.report({"INFO"}, f"Imported {len(imported)} LandXML surface(s)")
        return {"FINISHED"}


class WM_OT_landxml_import_validation(Operator):
    bl_idname = "wm.landxml_import_validation"
    bl_label = "LandXML Import Validation"
    bl_description = "Show the import validation summary"
    bl_options = {"INTERNAL"}

    source_name: StringProperty(options={"HIDDEN"})
    surface_count: IntProperty(options={"HIDDEN"})
    vertex_count: IntProperty(options={"HIDDEN"})
    face_count: IntProperty(options={"HIDDEN"})
    source_face_count: IntProperty(options={"HIDDEN"})
    invisible_face_count: IntProperty(options={"HIDDEN"})
    clipped_face_count: IntProperty(options={"HIDDEN"})
    curve_count: IntProperty(options={"HIDDEN"})
    point_count: IntProperty(options={"HIDDEN"})
    source_units: StringProperty(options={"HIDDEN"})
    skipped_face_count: IntProperty(options={"HIDDEN"})
    degenerate_face_count: IntProperty(options={"HIDDEN"})
    validation_enabled: BoolProperty(options={"HIDDEN"})

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=340)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Import completed", icon="CHECKMARK")
        layout.label(text=self.source_name)
        layout.separator()
        column = layout.column(align=True)
        column.label(text=f"Surfaces: {self.surface_count}")
        column.label(text=f"Vertices: {self.vertex_count:,}")
        column.label(text=f"Linework objects: {self.curve_count:,}")
        if self.point_count:
            column.label(text=f"Point records: {self.point_count:,}")
        column.label(text=f"Units: {self.source_units.replace('_', ' ').title()}")
        column.label(text=f"Source faces: {self.source_face_count:,}")
        if self.invisible_face_count:
            column.label(text=f"Excluded invisible faces: {self.invisible_face_count:,}")
        column.label(text=f"Imported faces: {self.face_count:,}")
        if self.clipped_face_count:
            column.label(text=f"Boundary-affected source faces: {self.clipped_face_count:,}")
        layout.separator()
        if self.validation_enabled:
            layout.label(text="Imported geometry validated", icon="CHECKMARK")
        else:
            layout.label(text="Imported geometry validation was skipped", icon="INFO")
        if self.skipped_face_count:
            layout.label(text=f"Skipped malformed faces: {self.skipped_face_count}", icon="ERROR")
        if self.degenerate_face_count:
            layout.label(text=f"Retained degenerate faces: {self.degenerate_face_count}", icon="ERROR")

    def execute(self, context):
        return {"FINISHED"}


class OBJECT_OT_landxml_validate_integrity(Operator):
    bl_idname = "object.landxml_validate_integrity"
    bl_label = "Validate LandXML TIN Integrity"
    bl_description = "Compare the raw mesh to its authoritative LandXML import fingerprint"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(context.active_object and "landxml_geometry_fingerprint" in context.active_object)

    def execute(self, context):
        obj = context.active_object
        expected = obj["landxml_geometry_fingerprint"]
        actual = object_geometry_fingerprint(obj)
        if actual != expected:
            self.report({"ERROR"}, "LandXML TIN differs from its imported geometry snapshot")
            return {"CANCELLED"}
        self.report({"INFO"}, "LandXML TIN matches its imported geometry snapshot")
        return {"FINISHED"}


class OBJECT_OT_landxml_apply_breaklines(Operator):
    bl_idname = "object.landxml_apply_breaklines"
    bl_label = "Use Breaklines on Surface"
    bl_description = "Mark TIN edges matching imported breaklines as sharp edges or UV seams"
    bl_options = {"REGISTER", "UNDO"}

    tolerance: FloatProperty(
        name="Match Tolerance",
        description="Maximum endpoint distance in meters when matching breakline segments to TIN edges",
        default=0.0001,
        min=0.000001,
        max=0.1,
        precision=6,
    )
    mark_sharp: BoolProperty(name="Mark Sharp", default=True)
    mark_seams: BoolProperty(name="Mark UV Seams", default=False)
    smooth_surface: BoolProperty(name="Smooth Surface", default=True)

    @classmethod
    def poll(cls, context):
        surface = context.active_object
        if not surface or "landxml_face_count" not in surface:
            return False
        import_name = surface.get("landxml_import_collection")
        return bool(import_name and any(
            obj.type == "CURVE"
            and obj.get("landxml_category") == "Breakline"
            and obj.get("landxml_import_collection") == import_name
            for obj in bpy.data.objects
        ))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mark_sharp")
        if self.mark_sharp:
            layout.prop(self, "smooth_surface")
        layout.prop(self, "mark_seams")
        layout.prop(self, "tolerance")

    def execute(self, context):
        surface = context.active_object
        import_name = surface.get("landxml_import_collection")
        breaklines = [
            obj for obj in bpy.data.objects
            if obj.type == "CURVE"
            and obj.get("landxml_category") == "Breakline"
            and obj.get("landxml_import_collection") == import_name
        ]
        try:
            matched, total, edge_count = apply_breaklines_to_surface(
                surface,
                breaklines,
                tolerance=self.tolerance,
                mark_sharp=self.mark_sharp,
                mark_seams=self.mark_seams,
                smooth_surface=self.smooth_surface,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        unmatched = total - matched
        level = {"WARNING"} if unmatched else {"INFO"}
        self.report(
            level,
            f"Marked {edge_count:,} mesh edges from {matched:,}/{total:,} breakline segments"
            + (f"; {unmatched:,} segments do not coincide with TIN edges" if unmatched else ""),
        )
        return {"FINISHED"}


def _landxml_selection(context) -> list[bpy.types.Object]:
    return [
        obj for obj in context.selected_objects
        if obj.type == "MESH" and "landxml_origin_easting" in obj
    ]


class OBJECT_OT_landxml_apply_orthophoto(Operator, ImportHelper):
    bl_idname = "object.landxml_apply_orthophoto"
    bl_label = "Apply Georeferenced Orthophoto"
    bl_description = (
        "Drape a north-up GeoTIFF, or an image with a world file, onto selected LandXML surfaces "
        "using their source coordinates"
    )
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".tif"
    filter_glob: StringProperty(default="*.tif;*.tiff;*.jpg;*.jpeg;*.png", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return bool(_landxml_selection(context))

    def execute(self, context):
        objects = _landxml_selection(context)
        try:
            bounds, total, outside = apply_orthophoto(objects, self.filepath)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        units = bounds.linear_units or "unverified units"
        if outside:
            self.report(
                {"WARNING"},
                f"Applied orthophoto to {len(objects)} surface(s) ({units}); "
                f"{outside:,} of {total:,} vertices lie outside the image",
            )
        else:
            self.report({"INFO"}, f"Applied orthophoto to {len(objects)} surface(s) ({units})")
        return {"FINISHED"}


class EXPORT_SCENE_OT_landxml_survey_reference(Operator, ExportHelper):
    bl_idname = "export_scene.landxml_survey_reference"
    bl_label = "Export LandXML Survey Reference"
    bl_description = "Write the active import's survey pivot and Cesium geographic anchor as JSON"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return bool(context.active_object and "landxml_survey_reference" in context.active_object)

    def execute(self, context):
        try:
            export_survey_reference(context.active_object, self.filepath)
        except (OSError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Survey reference exported; read sidecar warnings before Cesium placement")
        return {"FINISHED"}


class EXPORT_SCENE_OT_landxml_cesium_footprint(Operator, ExportHelper):
    bl_idname = "export_scene.landxml_cesium_footprint"
    bl_label = "Export Cesium Surface Footprint"
    bl_description = "Export the active TIN's exact visible footprint, islands and holes as geographic polygons"

    filename_ext = ".geojson"
    filter_glob: StringProperty(default="*.geojson", options={"HIDDEN"})
    coordinate_system: StringProperty(
        name="CRS Override (optional)",
        description="Leave blank to use the imported CRS, or search a zone / type EPSG:26996",
        search=_search_coordinate_system,
        search_options={"SUGGESTION"},
    )
    edge_offset_meters: _footprint_offset_property()
    simplify_meters: _footprint_simplify_property()

    @classmethod
    def poll(cls, context):
        return bool(context.active_object and context.active_object.get("landxml_category") == "Surface")

    def execute(self, context):
        try:
            result = export_cesium_footprint(
                context.active_object, self.filepath,
                horizontal_epsg=resolve_crs_entry(self.coordinate_system),
                edge_offset_meters=self.edge_offset_meters,
                simplify_meters=self.simplify_meters,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        counts = result["landxml"]
        self.report(
            {"INFO"},
            f"Exported {counts['island_count']} island(s), {counts['hole_count']} hole(s); "
            f"{result['cesium_unreal']['piece_count']} Cesium polygon actor(s). Use the Unreal import helper.",
        )
        return {"FINISHED"}


class EXPORT_SCENE_OT_landxml_unreal_package(Operator, ExportHelper):
    bl_idname = "export_scene.landxml_unreal_package"
    bl_label = "Export LandXML Unreal Package"
    bl_description = (
        "Export the active import's TIN surfaces as FBX with the survey pivot, "
        "plus survey reference JSON and Cesium footprints"
    )

    filename_ext = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={"HIDDEN"})
    selected_only: BoolProperty(
        name="Selected Surfaces Only",
        description="Export only selected surfaces from the active import instead of all of them",
        default=False,
    )
    include_footprints: BoolProperty(
        name="Cesium Footprints",
        description="Write one footprint GeoJSON per surface for Cesium polygon cutouts (needs a CRS)",
        default=True,
    )
    coordinate_system: StringProperty(
        name="CRS Override (optional)",
        description="Leave blank to use the imported CRS, or search a zone / type EPSG:26996",
        search=_search_coordinate_system,
        search_options={"SUGGESTION"},
    )
    edge_offset_meters: _footprint_offset_property()
    simplify_meters: _footprint_simplify_property()

    @classmethod
    def poll(cls, context):
        return bool(context.active_object and "landxml_survey_reference" in context.active_object)

    def execute(self, context):
        try:
            result = export_unreal_package(
                context.active_object, self.filepath,
                selected_only=self.selected_only,
                include_footprints=self.include_footprints,
                horizontal_epsg=resolve_crs_entry(self.coordinate_system),
                edge_offset_meters=self.edge_offset_meters,
                simplify_meters=self.simplify_meters,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        for warning in result["warnings"]:
            self.report({"WARNING"}, warning)
        self.report(
            {"INFO"},
            f"Exported {result['surface_count']} surface(s) to {Path(result['fbx']).name} "
            f"with survey JSON and {len(result['footprints'])} footprint(s)",
        )
        return {"FINISHED"}


def _menu_export(self, context):
    self.layout.operator(EXPORT_SCENE_OT_landxml_unreal_package.bl_idname, text="LandXML Unreal Package (.fbx + sidecars)")
    self.layout.operator(EXPORT_SCENE_OT_landxml_survey_reference.bl_idname, text="LandXML Survey Reference (.json)")
    self.layout.operator(EXPORT_SCENE_OT_landxml_cesium_footprint.bl_idname, text="Cesium Surface Footprint (.geojson)")


def _menu_import(self, context):
    self.layout.operator(
        IMPORT_SCENE_OT_landxml_tin.bl_idname,
        text="LandXML Data (.xml)",
    )


def _menu_object(self, context):
    self.layout.operator(OBJECT_OT_landxml_apply_breaklines.bl_idname)
    self.layout.operator(OBJECT_OT_landxml_validate_integrity.bl_idname)
    self.layout.operator(OBJECT_OT_landxml_apply_orthophoto.bl_idname)
    self.layout.operator(EXPORT_SCENE_OT_landxml_survey_reference.bl_idname)
    self.layout.operator(EXPORT_SCENE_OT_landxml_cesium_footprint.bl_idname)
    self.layout.operator(EXPORT_SCENE_OT_landxml_unreal_package.bl_idname)


_CLASSES = (
    IMPORT_SCENE_OT_landxml_tin,
    WM_OT_landxml_import_validation,
    OBJECT_OT_landxml_apply_breaklines,
    OBJECT_OT_landxml_validate_integrity,
    OBJECT_OT_landxml_apply_orthophoto,
    EXPORT_SCENE_OT_landxml_survey_reference,
    EXPORT_SCENE_OT_landxml_cesium_footprint,
    EXPORT_SCENE_OT_landxml_unreal_package,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)
    bpy.types.VIEW3D_MT_object.append(_menu_object)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    bpy.types.VIEW3D_MT_object.remove(_menu_object)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
