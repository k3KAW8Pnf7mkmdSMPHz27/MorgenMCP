"""Exercise release packaging and the mandatory provenance verification gate."""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts.build_bundle import stage_bundle
from scripts.verify_release import verify_release


def make_wheel(directory: Path, version: str = "1.2.3") -> Path:
    wheel = directory / f"morgenmcp-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"morgenmcp-{version}.dist-info/METADATA",
            f"Name: morgenmcp\nVersion: {version}\n",
        )
    return wheel


def test_stage_uses_exact_wheel_and_allowlisted_files(tmp_path: Path) -> None:
    wheel = make_wheel(tmp_path)
    stage = tmp_path / "stage"
    stage_bundle(wheel, "v1.2.3", stage)
    assert (stage / "wheels" / wheel.name).read_bytes() == wheel.read_bytes()
    assert json.loads((stage / "manifest.json").read_text())["version"] == "1.2.3"
    assert "morgenmcp==1.2.3" in (stage / "pyproject.toml").read_text()
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
        verify_release([artifact, second], bundle, "v1.2.3", "a" * 40)
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
    verify_release([artifact], bundle, "v1.2.3", "a" * 40)
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
        verify_release([artifact], tmp_path / "missing.json", "v1.2.3", "a" * 40)
