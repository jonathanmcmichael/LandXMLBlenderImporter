"""Install and exercise the manifest wheels for the current host platform."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import venv


EXTENSION_DIR = Path(__file__).resolve().parents[1] / "landxml_importer"
WHEEL_DIR = EXTENSION_DIR / "wheels"


def main() -> None:
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError(
            f"Platform wheels target Blender's CPython 3.13; got {sys.version.split()[0]}"
        )

    manifest = tomllib.loads(
        (EXTENSION_DIR / "blender_manifest.toml").read_text(encoding="utf-8")
    )
    requirements = []
    for wheel in manifest.get("wheels", ()):
        filename = Path(wheel).name
        name, version = filename.split("-", 2)[:2]
        if name in {"shapely", "pyproj", "certifi"}:
            requirement = f"{name}=={version}"
            if requirement not in requirements:
                requirements.append(requirement)

    with tempfile.TemporaryDirectory(prefix="landxml-wheel-test-") as directory:
        environment = Path(directory) / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            [str(python), "-m", "pip", "install", "numpy"],
            check=True,
        )
        subprocess.run(
            [
                str(python), "-m", "pip", "install",
                "--no-index", "--no-deps", "--find-links", str(WHEEL_DIR),
                *requirements,
            ],
            check=True,
        )

        subprocess.run(
            [
                str(python), "-c",
                "import certifi, pyproj, shapely; "
                "from pyproj import CRS; "
                "from shapely.geometry import Polygon; "
                "assert shapely.__version__ == '2.1.2'; "
                "assert pyproj.__version__ == '3.7.2'; "
                "assert CRS.from_epsg(2232).to_epsg() == 2232; "
                "assert Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]).area == 1; "
                "print(f'Shapely {shapely.__version__}; pyproj {pyproj.__version__}; "
                "certifi {certifi.__version__}')",
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
