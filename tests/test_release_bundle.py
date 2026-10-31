"""Exercise release packaging and the mandatory provenance verification gate."""

from __future__ import annotations

import json
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

from scripts.build_bundle import ROOT, stage_bundle
from scripts.verify_release import verify_release


def make_wheel(
    directory: Path,
    version: str = "1.2.3",
    requires_python: str | None = ">=3.12",
) -> Path:
    wheel = directory / f"morgenmcp-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"morgenmcp-{version}.dist-info/METADATA",
            f"Name: morgenmcp\nVersion: {version}\n"
            + (f"Requires-Python: {requires_python}\n" if requires_python else ""),
        )
    return wheel


@pytest.mark.parametrize("requires_python", [">=3.12", ">=3.13,<4"])
def test_stage_uses_exact_wheel_and_allowlisted_files(
    tmp_path: Path, requires_python: str
) -> None:
    wheel = make_wheel(tmp_path, requires_python=requires_python)
    stage = tmp_path / "stage"
    stage_bundle(wheel, "v1.2.3", stage)
    assert (stage / "wheels" / wheel.name).read_bytes() == wheel.read_bytes()
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.2.3"
    assert manifest["compatibility"]["runtimes"]["python"] == requires_python
    source = json.loads((ROOT / "desktop/manifest.json").read_text(encoding="utf-8"))
    assert manifest["long_description"] == source["long_description"]
    project = tomllib.loads((stage / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["requires-python"] == requires_python
    assert project["project"]["dependencies"] == ["morgenmcp==1.2.3"]
    assert {file.name for file in stage.iterdir()} == {
        "wheels",
        "manifest.json",
        "pyproject.toml",
        "server.py",
        "LICENSE",
        "NOTICE",
    }


@pytest.mark.parametrize("tag", ["v9.9.9", "v1.2.3rc1", "main", "v1.2.3;echo bad"])
def test_stage_rejects_mismatched_or_nonstable_tag(tmp_path: Path, tag: str) -> None:
    with pytest.raises(ValueError):
        stage_bundle(make_wheel(tmp_path), tag, tmp_path / "stage")
    assert not (tmp_path / "stage").exists()


def test_stage_rejects_missing_python_requirement(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Requires-Python"):
        stage_bundle(
            make_wheel(tmp_path, requires_python=None), "v1.2.3", tmp_path / "stage"
        )
    assert not (tmp_path / "stage").exists()


def test_provenance_failure_stops_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected signature must stop the gate rather than verify later files."""
    artifact, second, bundle = (
        tmp_path / name
        for name in ("first.mcpb", "second.whl", "provenance.sigstore.json")
    )
    for path in (artifact, second, bundle):
        path.write_text("test fixture")
    calls = []

    def reject(command: list[str], **kwargs: object) -> None:
        calls.append(command)
        assert kwargs["check"] is True
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", reject)
    with pytest.raises(subprocess.CalledProcessError):
        verify_release(artifact, second, bundle=bundle, tag="v1.2.3", commit="a" * 40)
    assert len(calls) == 1


def test_verification_pins_release_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not accept a valid signature from a different workflow, tag, or commit."""
    artifact, bundle = tmp_path / "release.mcpb", tmp_path / "provenance.sigstore.json"
    artifact.write_text("test fixture")
    bundle.write_text("test fixture")
    calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda command, **kwargs: calls.append(command)
    )
    verify_release(artifact, bundle=bundle, tag="v1.2.3", commit="a" * 40)
    command = calls[0]
    expected = {
        "--repo": "k3KAW8Pnf7mkmdSMPHz27/MorgenMCP",
        "--signer-workflow": "k3KAW8Pnf7mkmdSMPHz27/MorgenMCP/.github/workflows/release.yml",
        "--source-ref": "refs/tags/v1.2.3",
        "--source-digest": "a" * 40,
        "--cert-oidc-issuer": "https://token.actions.githubusercontent.com",
        "--predicate-type": "https://slsa.dev/provenance/v1",
        "--bundle": str(bundle.resolve()),
    }
    for option, value in expected.items():
        assert command[command.index(option) + 1] == value
    assert "--deny-self-hosted-runners" in command


def test_missing_bundle_fails_before_invoking_verifier(tmp_path: Path) -> None:
    artifact = tmp_path / "release.mcpb"
    artifact.write_text("test fixture")
    with pytest.raises(ValueError, match="Missing or empty"):
        verify_release(
            artifact,
            bundle=tmp_path / "missing.json",
            tag="v1.2.3",
            commit="a" * 40,
        )


@pytest.mark.parametrize("tag", ["v1.2.3rc1", "v1.2.3-beta", "1.2.3", "v1.2"])
def test_verify_release_rejects_nonstable_tag(tmp_path: Path, tag: str) -> None:
    artifact, bundle = tmp_path / "release.mcpb", tmp_path / "provenance.sigstore.json"
    artifact.write_text("test fixture")
    bundle.write_text("test fixture")
    with pytest.raises(ValueError, match="stable release tag"):
        verify_release(artifact, bundle=bundle, tag=tag, commit="a" * 40)
