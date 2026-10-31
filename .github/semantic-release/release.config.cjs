module.exports = {
  branches: ["main"],
  tagFormat: "v${version}",
  plugins: [
    [require.resolve("@semantic-release/commit-analyzer"), {preset: "conventionalcommits"}],
    [require.resolve("@semantic-release/exec"), {
      // GITHUB_TOKEN tag pushes do not trigger push workflows. Dispatch explicitly
      // at the tag to preserve the release workflow's OIDC and PyPI identities.
      publishCmd: "gh workflow run release.yml --ref ${nextRelease.gitTag}",
    }],
  ],
};
