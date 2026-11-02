"""Exercise release policy and local Git publication without calling GitHub."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts import release_tag


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("feat: calendar search", "v0.3.0"),
        ("feat(calendar): search", "v0.3.0"),
        ("fix: event parsing", "v0.2.2"),
        ("fix(events): parsing", "v0.2.2"),
        ("feat!: remove a tool", "v0.3.0"),
        ("refactor(api)!: remove a tool", "v0.3.0"),
        ("fix: output\n\nBREAKING CHANGE: remove a field", "v0.3.0"),
        ("docs: explain removal\n\nBREAKING-CHANGE: remove a field", "v0.3.0"),
        ("docs: setup", None),
        ("chore: tooling", None),
        ("docs: explain the word BREAKING", None),
        ("docs: examples\n\nfeat: example, not a commit subject", None),
        ("Merge branch 'feat: example'", None),
        ("feat: safely handle $(touch injected) and `commands`", "v0.3.0"),
        ("fix: handle Unicode café ☕", "v0.2.2"),
    ],
)
def test_commit_policy(message: str, expected: str | None) -> None:
    assert release_tag.next_tag("v0.2.1", [message]) == expected


def test_highest_bump_wins() -> None:
    assert release_tag.next_tag("v0.2.9", ["feat: search", "fix: parsing"]) == "v0.3.0"


def test_major_releases_only_after_manual_one_point_zero() -> None:
    assert release_tag.next_tag("v1.2.3", ["fix!: remove a field"]) == "v2.0.0"


@pytest.mark.parametrize("tag", ["v01.2.3", "v1.2.3rc1", "1.2.3", "v1.2"])
def test_invalid_baseline(tag: str) -> None:
    with pytest.raises(ValueError, match="stable"):
        release_tag.next_tag(tag, ["feat: search"])


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., str]:
    # All Git mutations stay in a temporary repo and its local bare remote.
    for name in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{name}_NAME", "Release test")
        monkeypatch.setenv(f"GIT_{name}_EMAIL", "release-test@example.invalid")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.chdir(tmp_path)

    def git(*args: str) -> str:
        return release_tag.run("git", *args)

    git("init", "--initial-branch=main")
    git("config", "commit.gpgsign", "false")
    git("config", "tag.gpgsign", "false")
    git("init", "--bare", "--initial-branch=main", str(tmp_path / "remote.git"))
    git("remote", "add", "origin", str(tmp_path / "remote.git"))
    git("commit", "--allow-empty", "-m", "chore: initial version")
    git("tag", "v0.2.1")
    git("push", "-u", "origin", "main", "--tags")
    return git


@pytest.fixture
def dispatch(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    real_run = release_tag.run

    def intercept(*args: str) -> str:
        if args[0] == "gh":
            calls.append(args)
            return ""
        return real_run(*args)

    monkeypatch.setattr(release_tag, "run", intercept)
    return calls


def test_tag_and_dispatch_exact_tested_commit(
    repo: Callable[..., str], dispatch: list[tuple[str, ...]]
) -> None:
    repo("commit", "--allow-empty", "-m", "feat: search $(touch injected)")
    repo("push", "origin", "main")
    commit = repo("rev-parse", "HEAD")
    repo("checkout", "--detach")
    assert release_tag.release_tag() == "v0.3.0"
    assert repo("cat-file", "-t", "v0.3.0") == "tag"
    assert repo("rev-parse", "v0.3.0^{}") == commit
    assert repo("ls-remote", "origin", "refs/tags/v0.3.0^{}").split()[0] == commit
    assert dispatch == [("gh", "workflow", "run", "release.yml", "--ref", "v0.3.0")]
    assert not Path("injected").exists()


def test_docs_do_not_tag_or_dispatch(
    repo: Callable[..., str], dispatch: list[tuple[str, ...]]
) -> None:
    repo("commit", "--allow-empty", "-m", "docs: setup")
    repo("push", "origin", "main")
    assert release_tag.release_tag() is None
    assert repo("tag", "--list") == "v0.2.1"
    assert not dispatch


def test_dry_run_does_not_tag_or_dispatch(
    repo: Callable[..., str], dispatch: list[tuple[str, ...]]
) -> None:
    repo("commit", "--allow-empty", "-m", "feat: search")
    repo("push", "origin", "main")
    assert release_tag.release_tag(dry_run=True) == "v0.3.0"
    assert repo("tag", "--list") == "v0.2.1"
    assert not dispatch


def test_latest_reachable_stable_version_is_numeric(
    repo: Callable[..., str], dispatch: list[tuple[str, ...]]
) -> None:
    for tag in ("v0.9.0", "v0.10.0", "v9.0.0rc1"):
        repo("tag", tag)
    repo("push", "origin", "--tags")
    repo("switch", "-c", "unreleased")
    repo("commit", "--allow-empty", "-m", "feat: unrelated branch")
    repo("tag", "v9.0.0")
    repo("push", "origin", "--tags")
    repo("switch", "main")
    repo("commit", "--allow-empty", "-m", "fix: parsing")
    repo("push", "origin", "main")
    assert release_tag.release_tag() == "v0.10.1"


def test_stale_ci_run_does_not_tag_or_dispatch(
    repo: Callable[..., str], dispatch: list[tuple[str, ...]]
) -> None:
    tested = repo("rev-parse", "HEAD")
    repo("commit", "--allow-empty", "-m", "feat: newer change")
    repo("push", "origin", "main")
    repo("checkout", "--detach", tested)
    assert release_tag.release_tag() is None
    assert repo("tag", "--list") == "v0.2.1"
    assert not dispatch


def test_no_stable_tag_fails_closed(
    repo: Callable[..., str], dispatch: list[tuple[str, ...]]
) -> None:
    repo("push", "origin", ":refs/tags/v0.2.1")
    repo("tag", "-d", "v0.2.1")
    with pytest.raises(ValueError, match="No reachable stable"):
        release_tag.release_tag()
    assert not dispatch


def test_existing_tag_is_never_moved(
    repo: Callable[..., str], dispatch: list[tuple[str, ...]]
) -> None:
    repo("switch", "-c", "other")
    repo("commit", "--allow-empty", "-m", "feat: unrelated branch")
    repo("tag", "v0.3.0")
    original = repo("rev-parse", "v0.3.0")
    repo("push", "origin", "--tags")
    repo("switch", "main")
    repo("commit", "--allow-empty", "-m", "feat: search")
    repo("push", "origin", "main")
    with pytest.raises(subprocess.CalledProcessError):
        release_tag.release_tag()
    assert repo("ls-remote", "origin", "refs/tags/v0.3.0").split()[0] == original
    assert not dispatch


def test_dispatch_failure_preserves_tag_and_does_not_increment_again(
    repo: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo("commit", "--allow-empty", "-m", "feat: search")
    repo("push", "origin", "main")
    real_run = release_tag.run

    def fail_dispatch(*args: str) -> str:
        if args[0] == "gh":
            raise subprocess.CalledProcessError(1, args)
        return real_run(*args)

    monkeypatch.setattr(release_tag, "run", fail_dispatch)
    with pytest.raises(subprocess.CalledProcessError):
        release_tag.release_tag()
    assert "refs/tags/v0.3.0" in repo("ls-remote", "--tags", "origin")
    assert release_tag.release_tag() is None
    assert repo("tag", "--list").splitlines() == ["v0.2.1", "v0.3.0"]
    assert "gh workflow run release.yml --ref v0.3.0" in capsys.readouterr().out


def test_push_failure_does_not_dispatch_and_allows_retry(
    repo: Callable[..., str],
    dispatch: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo("commit", "--allow-empty", "-m", "feat: search")
    repo("push", "origin", "main")
    real_run = release_tag.run

    def fail_push(*args: str) -> str:
        if args[:2] == ("git", "push"):
            raise subprocess.CalledProcessError(1, args)
        return real_run(*args)

    monkeypatch.setattr(release_tag, "run", fail_push)
    with pytest.raises(subprocess.CalledProcessError):
        release_tag.release_tag()
    assert repo("tag", "--list") == "v0.2.1"
    assert not dispatch
    monkeypatch.setattr(release_tag, "run", real_run)
    assert release_tag.release_tag() == "v0.3.0"
