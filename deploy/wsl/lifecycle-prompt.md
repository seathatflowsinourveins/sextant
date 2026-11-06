Lifecycle sweep for this repository, run by Orca's daily automation in its main checkout. Don't switch this checkout's branch: the lead works here.

1. Run `git fetch --prune origin`.
2. For each worktree in `orca worktree list --json` other than this checkout, find its branch's pull request: `gh pr list --head <branch> --state all --json number,state`. If it is `MERGED`, remove the worktree with `orca worktree rm --worktree branch:<branch> --delete-branch`. Keep a worktree that has an open pull request, has no pull request, has uncommitted changes or has commits that aren't on GitHub, and note why.
3. For each local branch whose upstream is gone, run `git branch -d <branch>`. Never use `-D`. Note any branch git refuses.
4. If `deploy/wsl/sextant.user-data` pins an older Orca than `gh release view -R stablyai/orca`, and that release is at least 3 days old, move the pin in its own Orca worktree: `orca worktree create --name orca-<tag> --base-branch origin/main`. Use the release's `.deb` URL and the sha256 digest that `gh release view <tag> -R stablyai/orca --json assets` publishes for it. Open the PR with `just pr`, from `.github/pull_request_template.md`, citing `stablyai/orca@<tag>` and its full commit SHA. A later sweep removes that worktree once the PR merges, and the lead then runs `just orca-update`.
5. If you kept anything or opened a PR, comment once on issue #35: what you removed, what you kept and why, and the PR. If nothing changed, post nothing.

Never print an environment variable's value. Never place an order or open a market-data stream.
