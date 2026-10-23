"""LandXML TIN Importer Blender extension."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from .blender_import import (
    apply_breaklines_to_surface,
    apply_orthophoto,
    import_landxml,
    object_geometry_fingerprint,
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
            ("AUTO", "From LandXML", "Use declared units; generic feet default to US survey feet with a warning"),
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
    pivot_easting: FloatProperty(name="Pivot Easting", default=0.0, precision=6)
    pivot_northing: FloatProperty(name="Pivot Northing", default=0.0, precision=6)
    pivot_elevation: FloatProperty(name="Pivot Elevation", default=0.0, precision=6)
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
            result = import_landxml(
                self.filepath,
                source_units=self.source_units,
                shift_to_origin=self.shift_to_origin,
                point_order=self.point_order,
                custom_origin=(self.pivot_easting, self.pivot_northing, self.pivot_elevation)
                if self.use_custom_pivot
                else None,
                validate_original_faces=self.validate_original_faces,
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


def _menu_import(self, context):
    self.layout.operator(
        IMPORT_SCENE_OT_landxml_tin.bl_idname,
        text="LandXML Data (.xml)",
    )


def _menu_object(self, context):
    self.layout.operator(OBJECT_OT_landxml_apply_breaklines.bl_idname)
    self.layout.operator(OBJECT_OT_landxml_validate_integrity.bl_idname)
    self.layout.operator(OBJECT_OT_landxml_apply_orthophoto.bl_idname)


_CLASSES = (
    IMPORT_SCENE_OT_landxml_tin,
    WM_OT_landxml_import_validation,
    OBJECT_OT_landxml_apply_breaklines,
    OBJECT_OT_landxml_validate_integrity,
    OBJECT_OT_landxml_apply_orthophoto,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.types.VIEW3D_MT_object.append(_menu_object)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(_menu_object)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)

