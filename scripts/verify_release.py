"""Verify release files against Sigstore provenance and the approved workflow identity."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

REPOSITORY = "k3KAW8Pnf7mkmdSMPHz27/MorgenMCP"
WORKFLOW = ".github/workflows/release.yml"


def verify_release(
    artifacts: list[Path],
    bundle: Path,
    tag: str,
    commit: str,
    repository: str = REPOSITORY,
) -> None:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Expected a stable release tag: vX.Y.Z")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", commit):
        raise ValueError("Expected the full 40-character release commit SHA")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected a GitHub owner/repository")
    if not artifacts:
        raise ValueError("At least one release artifact is required")
    for path in [bundle, *artifacts]:
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Missing or empty verification input: {path}")
    for artifact in artifacts:
        subprocess.run(
            [
                "gh",
                "attestation",
                "verify",
                str(artifact.resolve()),
                "--bundle",
                str(bundle.resolve()),
                "--repo",
                repository,
                "--signer-workflow",
                f"{repository}/{WORKFLOW}",
                "--source-ref",
                f"refs/tags/{tag}",
                "--source-digest",
                commit.lower(),
                "--cert-oidc-issuer",
                "https://token.actions.githubusercontent.com",
                "--predicate-type",
                "https://slsa.dev/provenance/v1",
                "--deny-self-hosted-runners",
            ],
            check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("artifacts", type=Path, nargs="+")
    args = parser.parse_args()
    verify_release(args.artifacts, args.bundle, args.tag, args.commit, args.repository)
