"""Stage a desktop bundle from the exact wheel built for a stable release."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stage_bundle(wheel: Path, tag: str, destination: Path) -> None:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Desktop releases require a stable vX.Y.Z tag")
    version = tag[1:]
    with zipfile.ZipFile(wheel) as archive:
        metadata_paths = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_paths) != 1:
            raise ValueError("Expected exactly one wheel METADATA file")
        metadata = BytesParser().parsebytes(archive.read(metadata_paths[0]))
    if metadata["Name"] != "morgenmcp" or metadata["Version"] != version:
        raise ValueError("Wheel name/version does not match the MorgenMCP release tag")

    # Use a fresh directory and an explicit allowlist, never the repository root.
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "wheels").mkdir()
    shutil.copy2(wheel, destination / "wheels" / wheel.name)
    for name in ("LICENSE", "NOTICE"):
        shutil.copy2(ROOT / name, destination / name)
    shutil.copy2(ROOT / "desktop/server.py", destination / "server.py")
    manifest = json.loads((ROOT / "desktop/manifest.json").read_text())
    manifest["version"] = version
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (destination / "pyproject.toml").write_text(
        "[project]\n"
        'name = "morgenmcp-desktop"\n'
        f'version = "{version}"\n'
        'requires-python = ">=3.12"\n'
        f'dependencies = ["morgenmcp=={version}"]\n\n'
        "[tool.uv.sources]\n"
        f'morgenmcp = {{ path = "wheels/{wheel.name}" }}\n'
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    stage_bundle(args.wheel, args.tag, args.destination)
