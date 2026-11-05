# Maintainer notes

The maintainer's working state. Read first each session; rewrite before ending it.

## State, 2026-11-04

The infrastructure was designed and built in a Claude conversation with the owner, then handed over to you, running in Claude Code. Governance is at v0.8.

**Trust model, agreed with the owner.** You maintain the org: CI, the checks and the template. The curator maintains the library. Governance, which holds the rules (yours among them) and **the core** (`governance/core/`, the only thing that starts agents and the only code that runs on the owner's machine), lives in the owner's personal account, outside the org. The owner alone maintains it. You read it at `/governance`; you don't change it or propose changes. If something in it seems wrong, tell the owner.

**The project folder:** `governance/` (the owner's clone: the core runs from it, and it's your read-only `/governance`), `repos/` (your `/repos`: one clone per org repo, named as on GitHub, nothing else), `.config/` (secrets), `data/` (ledger, session logs).

**`org-ci` is CI only now:** workflows, `scripts/`, `config/`, and the detector fixtures. The launcher, sandbox image, start scripts, token minter and kill switch moved into the core.

### Verified on GitHub
- Repos: `app-template`, the library and its workspace, `org-ci`, `alerts` (private). Library and template Pages are live. The old `instructions` branch should be gone from `app-template`, and `static-ai-apps/governance` should redirect to governance in the owner's account; check both.
- Forking within the org under a dot name works.
- The CI App's key works in `org-ci`.
- `create-app` creates a full repo pair, after the fix for the 409 GitHub returns while a new repo fills. Test app: `test-timer`.
- `pipeline` closes pull requests from strangers with the right comment.
- An IC pull request opened with the session tokens is found, validated in the isolated job, and blocked with the right reasons.

### Built but not yet verified for real
- The `self-test` workflow's first run on GitHub. It was running at handover; check it passed.
- The pass path: merge, then the re-bake, then the app appearing in the library.
- The agent image (`core.py build`). It has never been built.
- The core against real Docker and GitHub. Tested only with a fake docker, a mocked GitHub and local git repos (`governance/core/tests/test_core.py`).
- That `--disallowedTools Agent` switches off sub-agents in both sessions and your own container: ask for one and check it's refused.
- That `--append-system-prompt-file` works in Claude Code's interactive mode, for your own container. It's documented for `-p`; if it isn't accepted interactively, tell the owner: the core would need another way to give you your rules, such as writing them into your home's `~/.claude/CLAUDE.md` at each start.
- That `claude setup-token` and `CLAUDE_CODE_OAUTH_TOKEN` work for sessions in the container, and that sessions report an estimated cost and stop at `--max-budget-usd` on a subscription.
- A real IC session, and a real curator session.

### Cleanup the owner did during the move (check)
- `test-timer` pull request #2 closed, and branch `pipeline-check` deleted from `.test-timer`.
- `hello-world` is the owner's playground. CI ignores it (no workspace).

## Learned the hard way

Things that cost time to discover. Add to this list.

- **New repos fill in the background.** After creating a repo from a template, or forking, GitHub answers 404 and then 409 ("repository is empty") for a while. Wait for real content before the next step.
- **Pull requests between two repos in the same org** need `head=<branch>` (bare), `head_repo=static-ai-apps/.<app>` (full name), and `maintainer_can_modify=false`. The token opening them needs pull-request write on the published repo and contents read on the workspace.
- **Forking within the org under a dot name works.** `create-app` depends on it.
- **Claude Code's `--bare` mode doesn't use subscription logins,** so sessions run in normal mode, with an empty home directory in a throwaway container instead.

## Next

1. Check that `self-test` passed on the owner's latest push to `org-ci`, then work through the "not yet verified" list above.
2. Owner: build the image, run one IC session on `test-timer` (`core.py session ic test-timer --budget 2 --advice "…"`), and watch it end to end.
3. Then a full `core.py cycle`.

## Open items

Plans that change governance or the core (keeping the Claude token out of containers, scheduling, budget policy, Q in CI, a watchdog) are the owner's, in governance's ROADMAP.md. These are yours:

- A CI-only ruleset on every published repo, applied by `create-app` and re-applied by housekeeping. It's defense in depth: session tokens can't push to published repos anyway (INFRASTRUCTURE.md §4).
- Update the workflows' actions to current major versions and pin them to commit SHAs. GitHub warns about Node 20; Ubuntu 26 replaces `ubuntu-latest` from October 2026.
