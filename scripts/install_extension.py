"""Blender-side install step for the LandXML TIN Importer extension.

Run via install_extension.ps1, which builds the extension zip first.
This script only handles installing it into Blender, enabling it, and
saving preferences so it stays enabled across restarts.
"""

import glob
import os
import sys

import bpy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_MODULE = "bl_ext.user_default.landxml_tin_importer"


def main():
    zips = sorted(
        glob.glob(os.path.join(REPO_ROOT, "landxml_tin_importer-*.zip")),
        key=os.path.getmtime,
    )
    if not zips:
        print("ERROR: no landxml_tin_importer-*.zip found in repo root; build it first.")
        sys.exit(1)
    zip_path = zips[-1]

    bpy.ops.extensions.package_install_files(
        filepath=zip_path,
        repo="user_default",
        enable_on_install=True,
    )
    bpy.ops.preferences.addon_enable(module=ADDON_MODULE)
    bpy.ops.wm.save_userpref()
    print(f"Installed and enabled: {zip_path}")


main()
