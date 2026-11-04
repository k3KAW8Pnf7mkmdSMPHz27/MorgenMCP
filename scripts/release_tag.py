"""Tag Conventional Commit releases and dispatch the verified release workflow."""

from __future__ import annotations

import argparse
import re
import subprocess
from enum import IntEnum
from typing import NamedTuple

VERSION = re.compile(
    r"v(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)",
    re.ASCII,
)
HEADER = re.compile(r"(?P<type>[a-z]+)(?:\([^()\r\n]+\))?(?P<breaking>!)?: [^\r\n]+")
BREAKING = re.compile(r"^BREAKING(?: CHANGE|-CHANGE):[ \t]+\S", re.MULTILINE)


class Bump(IntEnum):
    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3


class Version(NamedTuple):
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, tag: str) -> Version:
        match = VERSION.fullmatch(tag)
        if not match:
            raise ValueError("Expected a stable vX.Y.Z release tag")
        return cls(int(match["major"]), int(match["minor"]), int(match["patch"]))

    def bump_major(self) -> Version:
        return Version(self.major + 1, 0, 0)

    def bump_minor(self) -> Version:
        return Version(self.major, self.minor + 1, 0)

    def bump_patch(self) -> Version:
        return Version(self.major, self.minor, self.patch + 1)

    def to_tag(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"


def run(*args: str) -> str:
    result = subprocess.run(
        args,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def next_tag(latest: str, messages: list[str]) -> str | None:
    version = Version.parse(latest)
    bump = Bump.NONE

    for message in messages:
        message = message.strip()
        header = HEADER.fullmatch(message.split("\n", 1)[0])
        if not header:
            continue

        if header.group("breaking") or BREAKING.search(message):
            bump = max(bump, Bump.MAJOR if version.major else Bump.MINOR)
        elif header.group("type") == "feat":
            bump = max(bump, Bump.MINOR)
        elif header.group("type") == "fix":
            bump = max(bump, Bump.PATCH)

    match bump:
        case Bump.MAJOR:
            return version.bump_major().to_tag()
        case Bump.MINOR:
            return version.bump_minor().to_tag()
        case Bump.PATCH:
            return version.bump_patch().to_tag()
        case Bump.NONE:
            return None


def release_tag(*, dry_run: bool = False) -> str | None:
    run("git", "fetch", "origin", "main", "--tags")
    commit = run("git", "rev-parse", "HEAD")
    if commit != run("git", "rev-parse", "FETCH_HEAD"):
        print("Skipping stale CI run: tested commit is no longer origin/main.")
        return None

    tags = run("git", "tag", "--merged", commit, "--list", "v*").splitlines()
    stable = [tag for tag in tags if VERSION.fullmatch(tag)]
    if not stable:
        raise ValueError("No reachable stable release tag; seed vX.Y.Z manually first")

    latest = max(stable, key=Version.parse)
    messages = run("git", "log", f"{latest}..{commit}", "--format=%B%x00").split("\0")
    tag = next_tag(latest, messages)

    if tag is None:
        print(
            f"No new release since {latest}. To retry publication of that tag: "
            f"gh workflow run release.yml --ref {latest}"
        )
        return None

    print(f"Next release: {latest} -> {tag} at {commit}")
    if not dry_run:
        run("git", "tag", "-a", tag, commit, "-m", f"Release {tag}")
        try:
            run("git", "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}")
        except subprocess.CalledProcessError:
            run("git", "tag", "-d", tag)
            raise
        run("gh", "workflow", "run", "release.yml", "--ref", tag)

    return tag


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without tagging"
    )
    args = parser.parse_args()
    try:
        release_tag(dry_run=args.dry_run)
    except (ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Release failed: {exc}\n")
