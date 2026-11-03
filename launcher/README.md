# Launcher interface

The launcher is the trusted program that starts agent sessions. It's run by the human owner, outside every agent's reach, and isn't part of this repo. This file specifies what it must do, so any harness can implement it.

## Sessions it starts

| Session | When | Preamble |
|---|---|---|
| Curator | On a schedule the owner sets | [`curator-preamble.md`](curator-preamble.md) |
| IC | On the curator's `launch` request | [`ic-preamble.md`](ic-preamble.md) |

The preamble is the session's first message. Fill the `{{…}}` fields and change nothing else.

## Requests it accepts from the curator

Only these two. Anything else is refused.

### `launch`

| Field | Rule |
|---|---|
| `repo` | An existing app: a published repo with a workspace (`.repo`). Not the library. |
| `advice` | Free text, at most 8,000 characters. |
| `budget` | Credits (estimated US dollars, GOVERNANCE.md §11), at most the configured per-session maximum. The sum of today's requests may exceed the pool; the queue simply stops when the pool runs out. |

The launcher:

1. Checks the fields and queues the request, in the order the curator sent them.
2. Generates a random marker (for example 24 random hex characters) and removes any occurrence of it from `advice`. The marker stops advice from faking the end of the advice block.
3. Mints two installation tokens from the IC GitHub App:
   - `repositories: [".repo"]`, `permissions: {contents: write}`
   - `repositories: ["repo"]`, `permissions: {pull_requests: write, contents: read}`

   Installation tokens expire after an hour, which is why sessions are limited to just under an hour: one pair of tokens lasts the whole session.
4. When the request reaches the front of the queue, starts the session with `ic-preamble.md`, filled in, and with three limits: the request's credits as an estimated-cost cap, about 200 turns, and just under an hour of wall-clock time. Claude Code enforces the first two itself; the launcher enforces the third.
5. When the session ends, for whatever reason, records its estimated cost, turns, duration and outcome in the ledger, along with any pull request it opened.
6. Dispatches the `pipeline` workflow in `org-ci` with input `repo`, so CI checks any pull request right away instead of within ten minutes.

### `create`

| Field | Rule |
|---|---|
| `name` | Checked again by `create_app.py`; see CURATOR.md §6 |
| `pitch` | Free text, at most 8,000 characters |

The launcher dispatches the `create-app` workflow in `org-ci` with these inputs and returns its result to the curator's next session.

## The daily cycle

1. Start the curator's session, capped at the curator allowance. Its preamble includes the pool for today and yesterday's ledger.
2. Collect its `launch` and `create` requests. Dispatch the `create` requests.
3. Run the `launch` queue one session at a time, in order, deducting each session's actual estimated cost from the pool. Skip a request whose credits exceed what's left.
4. Stop when the pool is spent, the queue is empty, or the owner's usage window is exhausted. Remaining requests expire; nothing carries over.

Only one session runs at a time, ever.

### Configuration (the human owner's)

| Setting | Starting guess |
|---|---|
| Curator allowance | $2 |
| Pool per day | $10 |
| Most credits any one session may receive | $3 |
| Turn limit per session | 200 |
| Time limit per session | 55 minutes |

## The ledger

One record per session: date, role, repo, credits granted, estimated cost, turns, duration, how it ended (finished, budget, turns, time, error), and the pull request it opened, if any. Keep it where the launcher runs; include the previous cycle's records in the curator's preamble.

## Curator sessions

Same as IC sessions, with the curator GitHub App, and with the library in place of the app:

- `repositories: [".static-ai-apps.github.io"]`, `permissions: {contents: write}`
- `repositories: ["static-ai-apps.github.io"]`, `permissions: {pull_requests: write, contents: read}`

After the session, dispatch `pipeline` with `repo: static-ai-apps.github.io`.

## What the launcher holds

- The private keys of the IC and curator GitHub Apps
- A credential that can dispatch workflows in `org-ci` (`actions: write` on that repo only)
- The budget ledger

No agent ever sees any of these.

## Stopping

Stopping the launcher stops all agent activity: no new sessions, no new tokens, and existing tokens expire within an hour. It's the first step of the kill switch (INFRASTRUCTURE.md on the instructions branch).
