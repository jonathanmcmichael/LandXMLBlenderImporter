"""LandXML TIN Importer Blender extension."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from .blender_import import import_landxml, object_geometry_fingerprint


class IMPORT_SCENE_OT_landxml_tin(Operator, ImportHelper):
    bl_idname = "import_scene.landxml_tin"
    bl_label = "Import LandXML TIN Surface"
    bl_description = "Import authoritative LandXML Points and Faces as Blender meshes"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".xml"
    filter_glob: StringProperty(default="*.xml;*.landxml", options={"HIDDEN"})

    source_units: EnumProperty(
        name="Source Units",
        description="Linear units used by the LandXML point coordinates",
        items=(
            ("METERS", "Meters", "Source coordinates are meters"),
            ("INTERNATIONAL_FEET", "International Feet", "One foot equals exactly 0.3048 meters"),
            ("US_SURVEY_FEET", "US Survey Feet", "One foot equals 1200/3937 meters"),
        ),
        default="US_SURVEY_FEET",
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
        name="Validate Original TIN Faces",
        description="Cancel the import if Blender does not retain the parsed LandXML vertex and face counts",
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
        bpy.ops.object.select_all(action="DESELECT")
        try:
            imported = import_landxml(
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

        skipped = sum(obj["landxml_skipped_face_count"] for obj in imported)
        degenerate = sum(obj["landxml_degenerate_face_count"] for obj in imported)
        bpy.ops.wm.landxml_import_validation(
            "INVOKE_DEFAULT",
            source_name=bpy.path.display_name_from_filepath(self.filepath),
            surface_count=len(imported),
            vertex_count=sum(obj["landxml_vertex_count"] for obj in imported),
            face_count=sum(obj["landxml_face_count"] for obj in imported),
            skipped_face_count=skipped,
            degenerate_face_count=degenerate,
            validation_enabled=self.validate_original_faces,
        )
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
        column.label(text=f"Faces: {self.face_count:,}")
        layout.separator()
        if self.validation_enabled:
            layout.label(text="Source topology validated", icon="CHECKMARK")
        else:
            layout.label(text="Source topology validation was skipped", icon="INFO")
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


def _menu_import(self, context):
    self.layout.operator(
        IMPORT_SCENE_OT_landxml_tin.bl_idname,
        text="LandXML TIN Surface (.xml)",
    )


def _menu_object(self, context):
    self.layout.operator(OBJECT_OT_landxml_validate_integrity.bl_idname)


_CLASSES = (
    IMPORT_SCENE_OT_landxml_tin,
    WM_OT_landxml_import_validation,
    OBJECT_OT_landxml_validate_integrity,
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

