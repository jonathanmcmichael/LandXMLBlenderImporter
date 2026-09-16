"""LandXML TIN Importer Blender extension."""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from .blender_import import import_landxml


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
    point_order: EnumProperty(
        name="Point Order",
        description="Coordinate order used by the LandXML <P> point values",
        items=(
            ("NEZ", "Northing, Easting, Elevation", "LandXML 1.2 standard order; most Civil 3D exports"),
            ("ENZ", "Easting, Northing, Elevation", "Non-standard order; use if the terrain appears mirrored or rotated"),
        ),
        default="NEZ",
    )

    def execute(self, context):
        bpy.ops.object.select_all(action="DESELECT")
        try:
            imported = import_landxml(
                self.filepath,
                source_units=self.source_units,
                shift_to_origin=self.shift_to_origin,
                point_order=self.point_order,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Imported {len(imported)} LandXML surface(s)")
        return {"FINISHED"}


def _menu_import(self, context):
    self.layout.operator(
        IMPORT_SCENE_OT_landxml_tin.bl_idname,
        text="LandXML TIN Surface (.xml)",
    )


_CLASSES = (IMPORT_SCENE_OT_landxml_tin,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)

