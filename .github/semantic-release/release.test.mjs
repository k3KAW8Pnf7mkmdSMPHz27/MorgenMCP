import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {mkdtemp, mkdir, writeFile, readFile, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {Writable} from "node:stream";
import {test} from "node:test";
import {fileURLToPath, pathToFileURL} from "node:url";
import semanticRelease from "semantic-release";
const configPath = fileURLToPath(new URL("./release.config.cjs", import.meta.url));

for (const [message, expected] of [
  ["feat: add calendar search", "0.3.0"],
  ["fix: correct event parsing", "0.2.2"],
  ["feat!: remove an old tool", "1.0.0"],
  ["docs: clarify setup", null],
  ["chore: update tooling", null],
  ["fix: change output\n\nBREAKING CHANGE: remove a field", "1.0.0"],
]) {
  test(message, async () => {
    const root = await mkdtemp(join(tmpdir(), "morgenmcp-version-"));
    const cwd = join(root, "repo");
    const remote = join(root, "remote.git");
    const bin = join(root, "bin");
    const dispatchLog = join(root, "dispatch.log");
    const env = {
      PATH: `${bin}:${process.env.PATH}`,
      HOME: process.env.HOME,
      TRIAL_DISPATCH_LOG: dispatchLog,
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_AUTHOR_NAME: "Release test",
      GIT_AUTHOR_EMAIL: "release-test@example.invalid",
      GIT_COMMITTER_NAME: "Release test",
      GIT_COMMITTER_EMAIL: "release-test@example.invalid",
    };
    const git = (...args) => execFileSync("git", args, {cwd, env, stdio: "pipe"}).toString().trim();
    try {
      await mkdir(cwd);
      await mkdir(bin);
      await writeFile(join(bin, "gh"), '#!/bin/sh\nprintf "%s\\n" "$@" > "$TRIAL_DISPATCH_LOG"\n', {mode: 0o755});
      git("init", "--bare", remote);
      git("init", "--initial-branch=main");
      git("config", "commit.gpgsign", "false");
      git("config", "tag.gpgsign", "false");
      git("remote", "add", "origin", remote);
      git("commit", "--allow-empty", "-m", "chore: initial version");
      git("tag", "v0.2.1");
      git("push", "-u", "origin", "main", "--tags");
      git("commit", "--allow-empty", "-m", message);
      git("push", "origin", "main");
      const githubCI = message === "feat: add calendar search";
      if (githubCI) {
        git("checkout", "--detach");
        Object.assign(env, {
          CI: "true", GITHUB_ACTIONS: "true", GITHUB_EVENT_NAME: "workflow_run",
          GITHUB_REF: "refs/heads/main", GITHUB_SHA: git("rev-parse", "HEAD"),
          GITHUB_REPOSITORY: "example/release-test",
        });
      }
      const quiet = () => new Writable({write(chunk, encoding, callback) {callback();}});
      const result = await semanticRelease(
        {extends: [configPath], repositoryUrl: pathToFileURL(remote).href, ci: githubCI},
        {cwd, env, stdout: quiet(), stderr: quiet()},
      );
      assert.equal(result ? result.nextRelease.version : null, expected);
      if (expected) {
        assert.equal(git("rev-parse", `v${expected}`), git("rev-parse", "HEAD"));
        assert.equal(await readFile(dispatchLog, "utf8"), `workflow\nrun\nrelease.yml\n--ref\nv${expected}\n`);
        assert.match(git("ls-remote", "--tags", "origin"), new RegExp(`refs/tags/v${expected.replaceAll('.', '\\.')}`));
      } else {
        assert.deepEqual(git("tag", "--list").split("\n"), ["v0.2.1"]);
        await assert.rejects(readFile(dispatchLog), {code: "ENOENT"});
      }
    } finally {
      await rm(root, {recursive: true, force: true});
    }
  });
}
