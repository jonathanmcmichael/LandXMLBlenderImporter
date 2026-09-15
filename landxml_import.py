import bpy
import xml.etree.ElementTree as ET
from pathlib import Path
from bpy.props import StringProperty, BoolProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper


def strip_namespace(tag):
    """Return XML tag name without namespace."""
    return tag.split("}")[-1]


def find_children_by_tag(root, tag_name):
    """Find all descendants matching a tag name, ignoring namespace."""
    return [
        elem for elem in root.iter()
        if strip_namespace(elem.tag) == tag_name
    ]


def import_landxml_surface(filepath, shift_to_origin=True):
    filepath = Path(filepath)

    tree = ET.parse(filepath)
    root = tree.getroot()

    # ---------------------------------------------------------
    # Find surfaces
    # ---------------------------------------------------------

    surfaces = [
        elem for elem in root.iter()
        if strip_namespace(elem.tag) == "Surface"
    ]

    if not surfaces:
        raise RuntimeError("No <Surface> elements found in LandXML file.")

    imported_objects = []

    for surface_index, surface in enumerate(surfaces):

        surface_name = surface.attrib.get(
            "name",
            f"LandXML_Surface_{surface_index + 1}"
        )

        print(f"Importing surface: {surface_name}")

        # ---------------------------------------------------------
        # Find points and faces for this surface
        # ---------------------------------------------------------

        point_elements = [
            elem for elem in surface.iter()
            if strip_namespace(elem.tag) == "P"
        ]

        face_elements = [
            elem for elem in surface.iter()
            if strip_namespace(elem.tag) == "F"
        ]

        if not point_elements:
            print(f"Skipping '{surface_name}': no points found.")
            continue

        if not face_elements:
            print(f"Skipping '{surface_name}': no faces found.")
            continue

        # ---------------------------------------------------------
        # Parse LandXML points
        #
        # Civil/LandXML commonly stores:
        #
        #     Northing Easting Elevation
        #
        # Blender expects:
        #
        #     X = Easting
        #     Y = Northing
        #     Z = Elevation
        # ---------------------------------------------------------

        points_by_id = {}

        for p in point_elements:

            point_id = p.attrib.get("id")

            if not point_id or not p.text:
                continue

            values = p.text.strip().split()

            if len(values) < 3:
                continue

            northing = float(values[0])
            easting = float(values[1])
            elevation = float(values[2])

            points_by_id[point_id] = (
                easting,
                northing,
                elevation
            )

        if not points_by_id:
            print(f"Skipping '{surface_name}': couldn't parse points.")
            continue

        # ---------------------------------------------------------
        # Establish local origin
        # ---------------------------------------------------------

        if shift_to_origin:

            eastings = [p[0] for p in points_by_id.values()]
            northings = [p[1] for p in points_by_id.values()]
            elevations = [p[2] for p in points_by_id.values()]

            origin_x = min(eastings)
            origin_y = min(northings)

            # Preserve actual elevation instead of shifting Z
            origin_z = 0.0

        else:
            origin_x = 0.0
            origin_y = 0.0
            origin_z = 0.0

        # ---------------------------------------------------------
        # Build vertex list and map LandXML IDs -> Blender indices
        # ---------------------------------------------------------

        vertices = []
        id_to_index = {}

        for point_id, coords in points_by_id.items():

            x, y, z = coords

            vertex = (
                x - origin_x,
                y - origin_y,
                z - origin_z
            )

            id_to_index[point_id] = len(vertices)
            vertices.append(vertex)

        # ---------------------------------------------------------
        # Faces
        #
        # Typical LandXML:
        #
        # <F>1 2 3</F>
        # ---------------------------------------------------------

        faces = []

        skipped_faces = 0

        for face in face_elements:

            if not face.text:
                continue

            ids = face.text.strip().split()

            if len(ids) < 3:
                continue

            try:
                indices = [
                    id_to_index[point_id]
                    for point_id in ids[:3]
                ]
            except KeyError:
                skipped_faces += 1
                continue

            faces.append(tuple(indices))

        if not faces:
            print(f"Skipping '{surface_name}': no valid faces.")
            continue

        # ---------------------------------------------------------
        # Create Blender mesh
        # ---------------------------------------------------------

        mesh = bpy.data.meshes.new(surface_name)

        mesh.from_pydata(
            vertices,
            [],
            faces
        )

        mesh.update()

        obj = bpy.data.objects.new(
            surface_name,
            mesh
        )

        bpy.context.collection.objects.link(obj)

        # ---------------------------------------------------------
        # Save Civil coordinates as custom properties
        # ---------------------------------------------------------

        obj["LandXML_Source"] = str(filepath)

        obj["LandXML_Origin_Easting"] = origin_x
        obj["LandXML_Origin_Northing"] = origin_y
        obj["LandXML_Origin_Elevation"] = origin_z

        obj["LandXML_Vertex_Count"] = len(vertices)
        obj["LandXML_Face_Count"] = len(faces)

        # ---------------------------------------------------------
        # Select imported object
        # ---------------------------------------------------------

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        imported_objects.append(obj)

        print(
            f"{surface_name}: "
            f"{len(vertices):,} vertices, "
            f"{len(faces):,} faces"
        )

        if skipped_faces:
            print(
                f"Warning: skipped {skipped_faces:,} "
                f"faces with invalid point references."
            )

        if shift_to_origin:
            print(
                "Civil coordinate origin stored as:\n"
                f"  Easting:  {origin_x}\n"
                f"  Northing: {origin_y}\n"
                f"  Elevation:{origin_z}"
            )

    if not imported_objects:
        raise RuntimeError(
            "LandXML contained no importable TIN surfaces."
        )

    return imported_objects


# =============================================================
# Blender Import Operator
# =============================================================

class IMPORT_OT_landxml_surface(Operator, ImportHelper):

    bl_idname = "import_scene.landxml_surface"
    bl_label = "Import LandXML Surface"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".xml"

    filter_glob: StringProperty(
        default="*.xml;*.landxml",
        options={'HIDDEN'}
    )

    shift_to_origin: BoolProperty(
        name="Shift Near Origin",
        description=(
            "Subtract the Civil Easting/Northing origin to avoid "
            "floating-point precision problems"
        ),
        default=True
    )

    def execute(self, context):

        # Clear selection
        bpy.ops.object.select_all(action='DESELECT')

        try:
            imported = import_landxml_surface(
                self.filepath,
                shift_to_origin=self.shift_to_origin
            )

        except Exception as exc:

            self.report(
                {'ERROR'},
                str(exc)
            )

            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Imported {len(imported)} LandXML surface(s)"
        )

        return {'FINISHED'}


# =============================================================
# Menu registration
# =============================================================

def menu_func_import(self, context):

    self.layout.operator(
        IMPORT_OT_landxml_surface.bl_idname,
        text="LandXML Surface (.xml)"
    )


classes = (
    IMPORT_OT_landxml_surface,
)


def register():

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(
        menu_func_import
    )


def unregister():

    bpy.types.TOPBAR_MT_file_import.remove(
        menu_func_import
    )

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()