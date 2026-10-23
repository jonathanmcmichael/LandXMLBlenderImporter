"""Blender-side install step for the LandXML TIN Importer extension.

Run via install_extension.ps1, which builds the extension zip first.
This script only handles installing it into Blender, enabling it, and
saving preferences so it stays enabled across restarts.
"""

import glob
import os
import platform
import sys

import bpy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_MODULE = "bl_ext.user_default.landxml_tin_importer"


def _platform_suffix():
    """Return the `--split-platforms` ZIP suffix for this machine, e.g. "windows_x64"."""
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    return f"{system}_{arch}"


def main():
    pattern = f"landxml_tin_importer-*-{_platform_suffix()}.zip"
    zips = sorted(
        glob.glob(os.path.join(REPO_ROOT, pattern)),
        key=os.path.getmtime,
    )
    if not zips:
        print(f"ERROR: no {pattern} found in repo root; build it first.")
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
