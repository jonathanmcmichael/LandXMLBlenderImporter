"""Download the wheels listed in the extension manifest from PyPI.

The manifest's ``wheels`` list is the source of truth; each file is fetched
from PyPI and checked against PyPI's published SHA-256 before it is kept.
Wheels already present with a matching hash are left alone.

Usage (from anywhere): python scripts/fetch_wheels.py
"""

import hashlib
import json
from pathlib import Path
import sys
import tomllib
import urllib.request

EXTENSION_DIR = Path(__file__).resolve().parents[1] / "landxml_importer"


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _pypi_files(name: str, version: str) -> dict[str, dict]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as response:
        release = json.load(response)
    return {item["filename"]: item for item in release["urls"]}


def main() -> int:
    manifest = tomllib.loads((EXTENSION_DIR / "blender_manifest.toml").read_text(encoding="utf-8"))
    releases: dict[tuple[str, str], dict[str, dict]] = {}
    for relative_path in manifest.get("wheels", ()):
        target = EXTENSION_DIR / relative_path
        name, version = target.name.split("-")[:2]
        files = releases.get((name, version))
        if files is None:
            files = releases[(name, version)] = _pypi_files(name, version)
        if target.name not in files:
            print(f"ERROR: {target.name} is not published on PyPI for {name} {version}")
            return 1
        expected = files[target.name]["digests"]["sha256"]

        if target.is_file() and _sha256(target) == expected:
            print(f"ok       {target.name}")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".part")
        urllib.request.urlretrieve(files[target.name]["url"], partial)
        if _sha256(partial) != expected:
            partial.unlink()
            print(f"ERROR: SHA-256 mismatch for {target.name}")
            return 1
        partial.replace(target)
        print(f"fetched  {target.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
