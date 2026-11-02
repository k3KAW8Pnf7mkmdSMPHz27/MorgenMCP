"""Tag Conventional Commit releases and dispatch the verified release workflow."""

from __future__ import annotations

import argparse
import re
import subprocess

VERSION = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
HEADER = re.compile(r"([a-z]+)(?:\([^()\r\n]+\))?(!)?: [^\r\n]+")
BREAKING = re.compile(r"^BREAKING(?: CHANGE|-CHANGE):[ \t]+\S", re.MULTILINE)


def run(*args: str) -> str:
    return subprocess.check_output(
        args, text=True, encoding="utf-8", errors="replace"
    ).strip()


def next_tag(latest: str, messages: list[str]) -> str | None:
    match = VERSION.fullmatch(latest)
    if not match:
        raise ValueError("Expected a stable vX.Y.Z release tag")
    major, minor, patch = map(int, match.groups())
    bump = 0
    for message in messages:
        message = message.strip()
        header = HEADER.fullmatch(message.split("\n", 1)[0])
        if not header:
            continue
        if header[2] or BREAKING.search(message):
            bump = max(bump, 3 if major else 2)
        elif header[1] == "feat":
            bump = max(bump, 2)
        elif header[1] == "fix":
            bump = max(bump, 1)
    if bump == 3:
        return f"v{major + 1}.0.0"
    if bump == 2:
        return f"v{major}.{minor + 1}.0"
    return f"v{major}.{minor}.{patch + 1}" if bump else None


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
    latest = max(stable, key=lambda tag: tuple(map(int, tag[1:].split("."))))
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
